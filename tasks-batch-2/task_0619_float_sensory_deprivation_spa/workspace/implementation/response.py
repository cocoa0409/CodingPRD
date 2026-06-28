"""Response envelope helpers — verbatim per SCAFFOLD §1.0 / PRD §2.2.

Success: { "meta": {api_request_id, api_request_timestamp, [pagination]},
           "response_type": "object"|"array", "data": ... }
Error:   { "meta": {...}, "response_type": "error",
           "data": { "error_id", "message" } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    chars = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(chars, k=20))


def _request_timestamp():
    # ISO 8601 UTC, three fractional digits, Z suffix (real wall-clock time
    # for the request meta — distinct from the logical clock).
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200, pagination=None):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
