"""Standard response envelope (PRD 2.2).

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO" [, pagination] },
    "response_type": "object" | "array", "data": {...} }

Error:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id", "message" } }
"""
import random
import string

from flask import jsonify

from clock import now_iso


def _request_id():
    rand = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + rand


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_object(data, status=200):
    return ok(data, status=status, response_type="object")


def ok_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return ok(items, status=200, response_type="array", pagination=pagination)


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
