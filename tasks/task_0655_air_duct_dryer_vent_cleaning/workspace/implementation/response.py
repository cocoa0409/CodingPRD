"""Standard response envelope helpers (PRD §2.2).

Success:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601",
              [pagination fields for lists] },
    "response_type": "object" | "array", "data": {} }

Error:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string

from flask import jsonify

from clock import clock, format_iso8601


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _request_timestamp():
    # Server-generated timestamp. PRD §2.2 shows a real ISO-8601 UTC timestamp
    # with three fractional digits on every response. This is the server clock
    # reading; we use the logical clock for determinism with the rest of the API.
    return format_iso8601(clock.now())


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, status=200):
    """Single-object success response."""
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    """List success response with pagination fields in meta."""
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
