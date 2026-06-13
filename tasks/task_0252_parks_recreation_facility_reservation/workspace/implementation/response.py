"""Standard response envelope helpers (PRD §2.2 / scaffold §1.0).

Success: { "meta": { api_request_id, api_request_timestamp, [pagination...] },
           "response_type": "object"|"array", "data": {...} }
Error:   { "meta": {...}, "response_type": "error",
           "data": { "error_id", "message" } }
"""
import random
import string
from datetime import timezone

from flask import jsonify

from clock import now as _clock_now


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _timestamp():
    # Use real wall-clock time for the request stamp, ISO 8601 UTC, 3 frac digits.
    from datetime import datetime
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
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
