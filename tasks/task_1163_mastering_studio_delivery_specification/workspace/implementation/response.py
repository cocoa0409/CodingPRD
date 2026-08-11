"""Standard response envelope helpers (PRD section 2.2)."""
import random
import string

from flask import jsonify

import db


def _request_id():
    return 'req_' + ''.join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(pagination=None):
    m = {
        'api_request_id': _request_id(),
        'api_request_timestamp': db.now_iso(),
    }
    if pagination:
        m.update(pagination)
    return m


def success(data, status=200):
    if data is None:
        data = {}
    payload = {'meta': _meta(), 'response_type': 'object', 'data': data}
    return jsonify(payload), status


def success_list(items, limit, offset, total):
    pagination = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': (offset + len(items)) < total,
    }
    payload = {'meta': _meta(pagination), 'response_type': 'array', 'data': items}
    return jsonify(payload), 200


def error_response(error_id, status, message):
    payload = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    return jsonify(payload), status
