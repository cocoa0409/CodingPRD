"""Standard response envelope helpers (PRD §2.2).

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
              [pagination fields for lists] },
    "response_type": "object" | "array",
    "data": {} }

Error:
  { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
    "response_type": "error",
    "data": { "error_id": ..., "message": ... } }
"""
import random
import string

from flask import jsonify

from db import iso_now


_ALNUM = string.ascii_letters + string.digits


def _request_id():
    # api_request_id is a server-generated id that starts with "req_".
    return "req_" + "".join(random.choices(_ALNUM, k=20))


def _meta():
    # api_request_timestamp: server-generated ISO 8601 UTC with three fractional
    # digits. This is wall-clock request time (not the logical clock).
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_now(),
    }


def success(data, status=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination is not None:
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
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, status=200, response_type="array", pagination=pagination)


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return body
