"""Standard response envelope helpers (scaffold §1.0 / PRD §2.2)."""
import uuid

from flask import jsonify

from util import now_iso


def _meta():
    return {
        'api_request_id': 'req_' + uuid.uuid4().hex[:24],
        'api_request_timestamp': now_iso(),
    }


def ok_object(data, status=200):
    body = {'meta': _meta(), 'response_type': 'object', 'data': data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    m = _meta()
    m['limit'] = limit
    m['offset'] = offset
    m['total_count'] = total_count
    m['has_more'] = (offset + len(items)) < total_count
    body = {'meta': m, 'response_type': 'array', 'data': items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    return jsonify(body), status
