"""Standard response envelope helpers (PRD §2.2, SCAFFOLD §1.0).

Success object: { meta:{api_request_id, api_request_timestamp, [pagination]},
                  response_type:"object"|"array", data:{...} }
Error:          { meta:{api_request_id, api_request_timestamp},
                  response_type:"error", data:{error_id, message} }
"""
from flask import jsonify
from clock import now_iso, request_id


def _meta(extra=None):
    m = {
        "api_request_id": request_id(),
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
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
