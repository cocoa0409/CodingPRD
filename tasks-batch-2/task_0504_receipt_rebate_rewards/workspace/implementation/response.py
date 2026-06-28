"""Response envelope helpers (PRD §2.2). All responses are wrapped in:
  { "meta": {...}, "response_type": "object"|"array"|"error", "data": ... }
"""
import random
import string

from flask import jsonify

from clock import format_iso


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(clock, extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": format_iso(clock.get()),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(clock, data, status=200):
    body = {
        "meta": _meta(clock),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(clock, items, limit, offset, total_count, status=200):
    meta = _meta(
        clock,
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
    )
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(clock, error_id, message, status):
    body = {
        "meta": _meta(clock),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
