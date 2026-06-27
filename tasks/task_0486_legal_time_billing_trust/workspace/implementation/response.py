"""Standard response envelope helpers (PRD §2.2).

Success:
  { "meta": {"api_request_id": "req_...", "api_request_timestamp": "ISO8601",
             [pagination fields for lists] },
    "response_type": "object" | "array",
    "data": {} | [] }

Error:
  { "meta": {"api_request_id": "req_...", "api_request_timestamp": "ISO8601"},
    "response_type": "error",
    "data": {"error_id": "...", "message": "..."} }
"""

import random
import string

from flask import jsonify

from clock import server_now_iso


def _request_id():
    rnd = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + rnd


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": server_now_iso(),
    }


def success(data, status=200, response_type="object", pagination=None):
    meta = _base_meta()
    if pagination:
        meta.update(pagination)
    body = {
        "meta": meta,
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


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
