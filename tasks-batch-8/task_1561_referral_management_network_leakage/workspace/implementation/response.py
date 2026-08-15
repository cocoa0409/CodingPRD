"""Response envelope helpers, matching SCAFFOLD response_envelope exactly.

Success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
List responses add limit/offset/total_count/has_more to meta.
"""
import uuid
from datetime import timezone

from flask import jsonify

from db import now


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def _meta():
    return {
        'api_request_id': 'req_' + uuid.uuid4().hex,
        'api_request_timestamp': fmt_dt(now()),
    }


def success_object(data, status=200):
    return jsonify({'meta': _meta(), 'response_type': 'object', 'data': data}), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta['limit'] = limit
    meta['offset'] = offset
    meta['total_count'] = total_count
    meta['has_more'] = (offset + len(items)) < total_count
    return jsonify({'meta': meta, 'response_type': 'array', 'data': items}), 200


def error_response(err):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': err.error_id, 'message': err.message},
    }
    return jsonify(body), err.http_status
