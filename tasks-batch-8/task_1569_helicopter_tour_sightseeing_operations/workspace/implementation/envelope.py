"""Response envelope helpers matching PRD section 2.2 exactly."""
import random
import string

from flask import jsonify

from store import fmt_ts, now


def _meta():
    rid = 'req_' + ''.join(random.choices(string.ascii_letters + string.digits, k=24))
    return {
        'api_request_id': rid,
        'api_request_timestamp': fmt_ts(now()),
    }


def success(data, status=200, response_type='object', pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {'meta': meta, 'response_type': response_type, 'data': data}
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    return jsonify(body), http_status
