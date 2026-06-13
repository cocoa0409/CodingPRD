"""Standard response-envelope helpers (PRD §2.2).

Success: { "meta": { api_request_id, api_request_timestamp, [pagination] },
           "response_type": "object"|"array", "data": {...} }
Error:   { "meta": { api_request_id, api_request_timestamp },
           "response_type": "error", "data": { error_id, message } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphanum, k=20))


def _timestamp():
    # ISO 8601 UTC with exactly three fractional digits, e.g. 2025-05-24T10:30:00.123Z
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(extra=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, pagination=None):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
