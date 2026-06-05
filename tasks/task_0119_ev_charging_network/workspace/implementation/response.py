"""Standard response envelope helpers (PRD §2.2).

Success object:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601" },
    "response_type": "object" | "array", "data": {...} }
List responses add limit/offset/total_count/has_more to meta.
Error:
  { "meta": {...}, "response_type": "error",
    "data": { "error_id": "...", "message": "..." } }
"""
import random
import string
from flask import jsonify

from clock import now_iso


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
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
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
