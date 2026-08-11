"""Response envelope helpers, per PRD section 2.2."""
import secrets

from flask import jsonify

from .db import fmt_wall, now_wall


def _meta(pagination=None):
    m = {
        'api_request_id': 'req_' + secrets.token_hex(8),
        'api_request_timestamp': fmt_wall(now_wall()),
    }
    if pagination is not None:
        m['limit'] = pagination['limit']
        m['offset'] = pagination['offset']
        m['total_count'] = pagination['total_count']
        m['has_more'] = pagination['has_more']
    return m


def ok(data, status=200, pagination=None):
    body = {
        'meta': _meta(pagination),
        'response_type': 'array' if pagination is not None else 'object',
        'data': data,
    }
    return jsonify(body), status


def err(error_id, message, status):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    return jsonify(body), status
