"""Standard response-envelope helpers.

Success: { "meta": {...}, "response_type": "object"|"array", "data": {...} }
Error:   { "meta": {...}, "response_type": "error", "data": {error_id, message} }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alnum, k=20))


def _now_iso_ms():
    # Server-generated wall-clock timestamp for the envelope, ISO8601 UTC w/ 3 frac digits.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso_ms(),
    }


def success(data, status=200, pagination=None):
    meta = _base_meta()
    if pagination is not None:
        meta.update(pagination)
        response_type = "array"
    elif isinstance(data, list):
        response_type = "array"
    else:
        response_type = "object"
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, http_status, message):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
