"""Standard response envelope (PRD §2.2, SCAFFOLD response_envelope).

success: { "meta": {api_request_id, api_request_timestamp, [pagination]},
           "response_type": "object"|"array", "data": {} }
error:   { "meta": {...}, "response_type": "error",
           "data": {"error_id": ..., "message": ...} }
"""
import random
import string

from flask import jsonify

import clock


def _request_id():
    # api_request_id starts with "req_" (PRD §2.2).
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphanum) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_iso(),
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


def array_response(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": _meta(meta_extra),
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
