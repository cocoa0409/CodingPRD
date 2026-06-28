"""Standard response envelope helpers (PRD §2.2, SCAFFOLD §1.0).

success: { "meta": {api_request_id, api_request_timestamp [, pagination]},
           "response_type": "object"|"array", "data": {} }
error:   { "meta": {...}, "response_type": "error",
           "data": {"error_id": ..., "message": ...} }
"""
import random
import string

from flask import jsonify

from clock import clock, format_iso8601_ms


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        # request timestamp tracks the server logical clock
        "api_request_timestamp": format_iso8601_ms(clock.now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, status=200, pagination=None, response_type="object"):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def object_response(data, status=200):
    return success(data, status=status, response_type="object")


def array_response(items, limit, offset, total_count, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(list(items), status=status, pagination=pagination,
                   response_type="array")


def error_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": api_error.error_id,
            "message": api_error.message,
        },
    }
    return jsonify(body), api_error.http_status
