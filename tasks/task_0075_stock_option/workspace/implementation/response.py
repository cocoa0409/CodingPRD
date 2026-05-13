"""Standard response envelope helpers."""

import random
import string
from datetime import datetime, timezone
from flask import jsonify


def _now_iso():
    # ISO 8601 UTC with three fractional digits, ending in 'Z'
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def success_response(data, http_status=200, response_type="object", pagination=None):
    extra = None
    if pagination is not None:
        extra = {
            "limit": pagination["limit"],
            "offset": pagination["offset"],
            "total_count": pagination["total_count"],
            "has_more": pagination["has_more"],
        }
    body = {
        "meta": _meta(extra),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def list_response(items, total_count, limit, offset):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success_response(items, http_status=200, response_type="array", pagination=pagination)


def error_response(error_id, http_status, message=""):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
