"""Standard response envelope helpers per PRD 2.2 / scaffold response_envelope."""
import secrets
import string
from flask import jsonify

from db import now_iso


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return 'req_' + ''.join(secrets.choice(alphabet) for _ in range(22))


def _meta(include_pagination=None):
    meta = {
        'api_request_id': _request_id(),
        'api_request_timestamp': now_iso(),
    }
    if include_pagination:
        meta.update(include_pagination)
    return meta


def success_object(data, status=200):
    body = {
        'meta': _meta(),
        'response_type': 'object',
        'data': data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    pag = {
        'limit': limit,
        'offset': offset,
        'total_count': total_count,
        'has_more': has_more,
    }
    body = {
        'meta': _meta(pag),
        'response_type': 'array',
        'data': items,
    }
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {
            'error_id': error_id,
            'message': message,
        },
    }
    return jsonify(body), http_status
