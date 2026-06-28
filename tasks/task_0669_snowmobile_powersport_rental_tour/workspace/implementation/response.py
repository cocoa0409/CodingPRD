"""Response envelope helpers (PRD §2.2, SCAFFOLD §1.0).

Success:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601",
              [pagination fields for lists] },
    "response_type": "object" | "array", "data": {} }
Error:
  { "meta": { ... }, "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alnum, k=20))


def _timestamp():
    # ISO 8601 UTC with exactly three fractional digits (PRD §2.2/§2.4).
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
    }
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
