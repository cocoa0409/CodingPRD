"""Standard response envelope helpers (PRD 2.2). The envelope is:
  { "meta": {api_request_id, api_request_timestamp [, pagination]},
    "response_type": "object"|"array"|"error", "data": {...} }
"""
import random
import string

from flask import jsonify

import clock

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choices(_ALPHANUM, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


# Fields that are internal bookkeeping and must never appear in API output.
_HIDDEN = ("_seq",)


def _public(obj):
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if k not in _HIDDEN}
    return obj


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _public(data) if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
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
        "data": [_public(it) for it in items],
    }
    return jsonify(body), status


def empty_response(status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": {},
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
