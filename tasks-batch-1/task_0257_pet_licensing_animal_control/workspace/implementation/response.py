"""Standard response envelope (PRD §2.2, SCAFFOLD §1.0 — EMIT VERBATIM).

success: { "meta": {api_request_id, api_request_timestamp[, pagination]},
           "response_type": "object"|"array", "data": {} }
error:   { "meta": {...}, "response_type": "error",
           "data": { "error_id", "message" } }
"""
import random
import string

from flask import jsonify

from db import now_iso


def _request_id():
    alphanum = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(random.choice(alphanum) for _ in range(20))


def _meta(pagination=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def object_response(data, status=200):
    return success(data, status=status, response_type="object")


def array_response(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, status=200, response_type="array", pagination=pagination)


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
