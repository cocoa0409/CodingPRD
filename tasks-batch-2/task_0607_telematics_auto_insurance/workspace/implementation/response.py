"""Standard response envelope (PRD §2.2).

Success: { meta: {...}, response_type: "object"|"array", data: ... }
Error:   { meta: {...}, response_type: "error", data: { error_id, message } }
"""
import random
import string

from flask import jsonify

import clock


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return f"req_{suffix}"


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.iso_now(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
