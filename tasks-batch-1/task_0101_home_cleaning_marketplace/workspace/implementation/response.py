"""Standard response envelope per PRD §2.2 / scaffold response_envelope.

success: { "meta": {api_request_id, api_request_timestamp, [pagination]},
           "response_type": "object"|"array", "data": {...} }
error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error",
           "data": {"error_id": ..., "message": ...} }
"""
from datetime import datetime, timezone

from flask import jsonify

from util import new_request_id, format_iso


def _base_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": format_iso(datetime.now(timezone.utc)),
    }


def success(data, status=200, response_type="object", pagination=None):
    meta = _base_meta()
    if pagination:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_success(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, status=200, response_type="array", pagination=pagination)


def error(error_id, http_status, message):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
