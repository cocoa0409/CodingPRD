"""Standard response envelope helpers (PRD §2.2).

Success:
  { "meta": {api_request_id, api_request_timestamp[, pagination...]},
    "response_type": "object" | "array", "data": {...} }
Error:
  { "meta": {api_request_id, api_request_timestamp},
    "response_type": "error", "data": {error_id, message} }
"""
import random
import string

from flask import jsonify

from timeutil import now_iso


def _request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alnum, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
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


def list_response(items, limit, offset, total_count, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, status=status, response_type="array", pagination=pagination)


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
