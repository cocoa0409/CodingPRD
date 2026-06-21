"""Response envelope helpers — exact field names from SCAFFOLD response_envelope
and PRD §2.2.

success: { "meta": { api_request_id, api_request_timestamp, [pagination] },
           "response_type": "object"|"array", "data": {} }
error:   { "meta": { api_request_id, api_request_timestamp },
           "response_type": "error", "data": { error_id, message } }
"""
from flask import jsonify
from util import new_request_id, now_iso


def _meta(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_array(items, limit, offset, total_count, status=200):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
