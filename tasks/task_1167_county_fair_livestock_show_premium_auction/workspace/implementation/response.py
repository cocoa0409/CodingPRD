"""Standard response envelope per scaffold §1.0 / PRD §2.2."""
import uuid
from flask import jsonify

from db import now_iso


def _meta():
    return {
        'api_request_id': 'req_' + uuid.uuid4().hex[:24],
        'api_request_timestamp': now_iso(),
    }


def success_object(data, status=200):
    body = {'meta': _meta(), 'response_type': 'object', 'data': data}
    return jsonify(body), status


def success_list(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta['limit'] = limit
    meta['offset'] = offset
    meta['total_count'] = total
    meta['has_more'] = (offset + len(page)) < total
    body = {'meta': meta, 'response_type': 'array', 'data': page}
    return jsonify(body), 200


def error_response(api_error):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': api_error.error_id, 'message': api_error.message},
    }
    return jsonify(body), api_error.http_status
