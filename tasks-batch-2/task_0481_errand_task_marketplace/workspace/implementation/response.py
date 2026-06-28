"""Standard response envelope helpers (PRD §2.2, SCAFFOLD §1.0).

Success: { "meta": {api_request_id, api_request_timestamp, [pagination]},
           "response_type": "object"|"array", "data": {...} }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error",
           "data": {error_id, message} }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _now_iso_millis():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso_millis(),
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


def object_response(data, status=200):
    return success(data, status=status, response_type="object")


def array_response(items, status=200, pagination=None):
    return success(items, status=status, response_type="array", pagination=pagination)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
