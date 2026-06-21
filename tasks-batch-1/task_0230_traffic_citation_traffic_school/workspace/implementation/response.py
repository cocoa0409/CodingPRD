"""Standard response-envelope helpers, per PRD §2.2.

Success:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601",
              [pagination fields for lists] },
    "response_type": "object" | "array", "data": ... }

Error:
  { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
    "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _now_iso():
    # ISO 8601 UTC with exactly three fractional digits, trailing Z.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, pagination=None):
    """data is a dict (object) or list (array)."""
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
