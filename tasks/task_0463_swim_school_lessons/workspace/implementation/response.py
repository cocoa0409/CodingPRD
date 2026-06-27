"""Standard response envelope helpers. PRD 2.2 / scaffold 1.0.

Success: { "meta": {api_request_id, api_request_timestamp [+pagination]},
           "response_type": "object" | "array", "data": {} }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {error_id, message} }
"""
import random
import string

from flask import jsonify

from clock import clock
from db import iso


def _request_id():
    # PRD 2.2: server-generated unique identifier that starts with 'req_'.
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        # PRD 2.2: ISO 8601 UTC timestamp with three fractional digits (logical clock).
        "api_request_timestamp": iso(clock.now()),
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
    # PRD 2.3: pagination fields surface inside meta.
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
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
