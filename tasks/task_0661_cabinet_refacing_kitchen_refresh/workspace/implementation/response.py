"""Standard response envelope helpers (PRD §2.2)."""
import random
import string

from flask import jsonify

from clock import format_iso8601_ms
from db import store


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": format_iso8601_ms(store.clock.now),
    }
    if extra:
        m.update(extra)
    return m


# Fields that are internal bookkeeping and must never appear in responses.
_HIDDEN = ("_seq",)


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if k not in _HIDDEN}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _clean(data) if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": _clean(items),
    }
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
