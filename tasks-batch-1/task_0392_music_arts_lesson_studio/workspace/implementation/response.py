"""Response envelope helpers. Envelope shape fixed per PRD §2.2 / SCAFFOLD §1.0:
  success: { "meta": { api_request_id, api_request_timestamp, [pagination] },
             "response_type": "object"|"array", "data": {...} }
  error:   { "meta": {...}, "response_type": "error",
             "data": { error_id, message } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    chars = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(chars, k=20))


def _now_iso():
    # ISO 8601 UTC with three fractional digits.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, status=200, is_array=False, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_array else "object",
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
