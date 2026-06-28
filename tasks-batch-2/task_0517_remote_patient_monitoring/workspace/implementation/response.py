"""Standard response envelope helpers (PRD §2.2).

success:
  { "meta": {"api_request_id": "req_xxx", "api_request_timestamp": "ISO8601",
             [pagination fields for lists]},
    "response_type": "object" | "array", "data": {} }
error:
  { "meta": {...}, "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string

from flask import jsonify

from clock import clock, format_ts

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choices(_ALPHANUM, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": format_ts(clock.now()),
    }
    if extra:
        m.update(extra)
    return m


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
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
