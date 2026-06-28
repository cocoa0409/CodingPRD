"""Standard response envelope helpers (PRD §2.2)."""
import random
import string

from flask import jsonify

from db import iso_ts
from clock import clock


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return f"req_{suffix}"


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_ts(clock.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def list_response(items, limit, offset, total_count, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, status=status, response_type="array", pagination=pagination)


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
