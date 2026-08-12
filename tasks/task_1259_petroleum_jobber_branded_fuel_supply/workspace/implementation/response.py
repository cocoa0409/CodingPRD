"""Response envelope helpers — exact structure from SCAFFOLD §1.0 / PRD §2.2."""
import secrets
import string

from flask import jsonify

from db import fmt_ts, wall_now


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return 'req_' + ''.join(secrets.choice(alphabet) for _ in range(20))


def _meta(pagination=None):
    m = {
        'api_request_id': _request_id(),
        'api_request_timestamp': fmt_ts(wall_now()),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def ok_object(data, status=200):
    body = {'meta': _meta(), 'response_type': 'object', 'data': data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta = _meta({
        'limit': limit,
        'offset': offset,
        'total_count': total_count,
        'has_more': has_more,
    })
    return jsonify({'meta': meta, 'response_type': 'array', 'data': items}), 200


def error_response(api_err):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': api_err.error_id, 'message': api_err.message},
    }
    return jsonify(body), api_err.http_status
