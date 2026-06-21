"""Standard response envelope (SCAFFOLD §1.0 / PRD §2.2).

Success: { "meta": { api_request_id, api_request_timestamp [, pagination] },
           "response_type": "object"|"array", "data": {...}|[...] }
Error:   { "meta": { api_request_id, api_request_timestamp },
           "response_type": "error", "data": { error_id, message } }

api_request_timestamp is an ISO 8601 UTC timestamp with three fractional digits
stamped from the logical clock (PRD §2.2 + §2.5).
"""

import random
import string

from flask import jsonify

from db import db


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
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


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
