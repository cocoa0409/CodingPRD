"""Standard response envelope (PRD 2.2).

Success:  { "meta": { api_request_id, api_request_timestamp [, pagination] },
            "response_type": "object" | "array", "data": {...} }
Error:    { "meta": { api_request_id, api_request_timestamp },
            "response_type": "error",
            "data": { "error_id": "...", "message": "..." } }
"""

import random
import string

from flask import jsonify

from db import store


def _request_id():
    # Server-generated unique identifier that starts with 'req_' (PRD 2.2).
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        # ISO 8601 UTC timestamp with three fractional digits, minted from the
        # logical clock (PRD 2.7: never falls back to real-world time).
        "api_request_timestamp": store.clock.now_iso_ms(),
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
    # Pagination fields live inside meta (PRD 2.3).
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
