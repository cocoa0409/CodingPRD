"""Standard response envelope helpers matching the scaffold's
response_envelope section exactly:

success: { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
           "response_type": "object" | "array", "data": {} }
error:   { "meta": { ... }, "response_type": "error",
           "data": { "error_id": "...", "message": "..." } }
pagination fields in meta: limit, offset, total_count, has_more
"""

from flask import jsonify
import db


def _meta():
    return {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.now_display_iso(),
    }


def success_object(data, status_code=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status_code


def success_list(items, limit, offset, total_count, status_code=200):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + limit) < total_count
    body = {
        "meta": m,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status_code


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
