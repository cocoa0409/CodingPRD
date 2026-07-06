"""Standard response envelope (PRD §2.2)."""
import random
import string
from flask import jsonify

from clock import now_iso_real


def _request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alnum) for _ in range(20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        # Wall-clock timestamp of the API request itself (NOT the logical clock).
        "api_request_timestamp": now_iso_real(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    """Single-object success envelope (response_type 'object')."""
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    """Array success envelope (response_type 'array') with pagination meta."""
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
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
