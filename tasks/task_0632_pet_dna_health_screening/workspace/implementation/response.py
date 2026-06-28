"""Response envelope helpers (SCAFFOLD response_envelope / PRD §2.2).

Success:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601", [pagination] },
    "response_type": "object" | "array", "data": {} }
Error:
  { "meta": { ... }, "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string
from flask import jsonify

from clock import clock, format_iso8601


def _request_id():
    # api_request_id starts with req_ (PRD §2.2)
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        # server-generated ISO 8601 UTC timestamp with three fractional digits.
        # Driven by the logical clock, never wall-clock time.
        "api_request_timestamp": format_iso8601(clock.now()),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_success(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, status=200, response_type="array", pagination=pagination)


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
