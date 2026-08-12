"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""
import random
import string

from flask import jsonify

from db import wall_now_iso


def _request_id():
    return 'req_' + ''.join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta_base():
    return {
        'api_request_id': _request_id(),
        'api_request_timestamp': wall_now_iso(),
    }


def ok_object(data, code=200):
    body = {'meta': _meta_base(), 'response_type': 'object', 'data': data}
    return jsonify(body), code


def ok_list(items, limit, offset, total_count):
    meta = _meta_base()
    meta['limit'] = limit
    meta['offset'] = offset
    meta['total_count'] = total_count
    meta['has_more'] = (offset + len(items)) < total_count
    body = {'meta': meta, 'response_type': 'array', 'data': items}
    return jsonify(body), 200


def err_response(error_id, status, message):
    body = {
        'meta': _meta_base(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    return jsonify(body), status
