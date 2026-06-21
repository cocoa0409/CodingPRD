"""Standard response envelope helpers (PRD §2.2, SCAFFOLD §1.0).

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
              [pagination fields for lists] },
    "response_type": "object" | "array", "data": {...} | [...] }

Error:
  { "meta": { "api_request_id": "...", "api_request_timestamp": "..." },
    "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""

import random
import string

from flask import jsonify

from clock import iso8601


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(now_dt, extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso8601(now_dt),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status, now_dt, response_type="object", pagination=None):
    body = {
        "meta": _meta(now_dt, pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def object_response(data, status, now_dt):
    return success(data, status, now_dt, response_type="object")


def array_response(items, total_count, limit, offset, now_dt):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, 200, now_dt, response_type="array", pagination=pagination)


def error_response(error_id, message, status, now_dt):
    body = {
        "meta": _meta(now_dt),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
