#!/usr/bin/env python
# !coding=utf8
from __future__ import absolute_import
import json
import logging
import re
import requests
from requests import Session
from requests.exceptions import RequestException
import sys
from time import sleep

from urlparse import urljoin



log = logging.getLogger(__name__)

JENKINS_CRUMB_API = "https://{}:\"{}\"@{}/crumbIssuer/api/xml?xpath=concat(//crumbRequestField,\":\",//crumb)"
JENKINS_JOB_API = re.compile(r'https://([^\s]*)/job')

def submit_sessions(**kwargs):
    print(kwargs)
    session = kwargs['session']
    job_request = kwargs['job_request']
    job_auth = requests.auth.HTTPBasicAuth(kwargs['username'], kwargs['password'])
    job_submit_url = urljoin(
        job_request['server_url'],
        'build' if kwargs is None else 'buildWithParameters')
    print(job_submit_url)
    status = True
    message = "success"
    try:
        jks_server = 'jf1atjenkins.ostc.intel.com'
        res = JENKINS_JOB_API.findall(kwargs['job_submit_url'])
        if res:
            jks_server = res[0]
        crumb_url = JENKINS_CRUMB_API.format(kwargs['username'], kwargs['password'], jks_server)
        r = session.get(crumb_url)
        r.raise_for_status()
        session.headers.update({'Jenkins-Crumb': r.content.split(':')[1]})
    except RequestException as exc:
        status = False
        message = 'Failed to get token for %s : %s' % (kwargs['username'], exc.message)
    try:
        r = session.post(url=job_submit_url, params=kwargs, auth=job_auth)
        r.raise_for_status()
    except RequestException as exc:
        status = False
        message = 'Failed to trigger a Jenkins build:{}'.format(exc.message)
    # Polling the build request till the build starts.
    job_request_url = r.headers.get('Location')
    if job_request_url is None:
        status = False
        message = 'Cannot get build request information: the "Location" header is missing from Jenkins HTTP response: {}"'.format(r.content) 

    job_request_url = urljoin(job_request_url, 'api', 'json')
    log.info('Polling queued task at: %r', job_request_url)
    backoff = 0
    sleep_time = 0
    max_total_sleep_time = 600
    while True:
        try:
            r = session.get(job_request_url)
            r.raise_for_status()
        except RequestException as exc:
            status = False
            message = exc.message
        try:
            jenkins_task = r.json()
        except ValueError:
            status = False
            message = 'Cannot decode JSON response:{}'.format(r.content)
        log.debug('Jenkins task: %r', jenkins_task)
        if 'task' not in jenkins_task:
            status = False
            message = 'The object pointed to at %r does not look like a valid task, aborting: %r' % (job_request_url, jenkins_task)
        try:
            job_request['job_url'] = jenkins_task['executable']['url']
        except TypeError as exc:
            try:
                if jenkins_task.get('cancelled', False):
                    status = False
                    message = 'The task has been cancelled.'
            except AttributeError:
                # We definitely are in bad luck!
                status = False
                message = 'Invalid task object from Jenkins:{}'.format(jenkins_task)
            finally:
                message ='Unable to get build URL'
        except KeyError:
            backoff = min(kwargs['max_backoff'], backoff + (backoff // 2) + 1)
            sleep_time += backoff
            if sleep_time <= max_total_sleep_time:
                log.info('Waiting for Jenkins build to start; sleep %s', backoff)
                sleep(backoff)
            else:
                status = False
                message = 'Out of max sleep time to wait the response from jenkins and return the server url instead'
                job_request['job_url'] = job_request['server_url']
                break
        else:
            json.dumpfile(job_request, kwargs['job_request_pname'])
    job_url = job_request['job_url']
    return status, message, job_url

