"""Standard response envelope per scaffold Section 1.0 and PRD 2.2.

Success: { "meta": {api_request_id, api_request_timestamp [, pagination]},
           "response_type": "object" | "array", "data": ... }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {error_id, message} }
"""
from flask import jsonify

from util import new_request_id, now_ts


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_ts(),
    }


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_array(items, status=200):
    """Array response without pagination fields (non-paginated list endpoints)."""
    body = {
        "meta": _meta(),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def success_list(items, total_count, limit, offset, status=200):
    """Paginated list response: meta carries limit/offset/total_count/has_more."""
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id: str, message: str, status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
