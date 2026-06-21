"""Standard response envelope helpers (PRD §2.2).

Success:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": ISO8601,
              [pagination fields for lists] },
    "response_type": "object" | "array", "data": {...} }

Error:
  { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
    "response_type": "error", "data": { "error_id": ..., "message": ... } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    chars = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(chars, k=20))


def _now_iso():
    # Server-generated wall-clock timestamp for the envelope, ISO 8601 UTC, 3
    # fractional digits, Z suffix. This is the response timestamp (not the
    # logical domain clock).
    return _iso(datetime.now(timezone.utc))


def _iso(dt):
    """Format a datetime as ISO 8601 UTC with exactly 3 fractional digits + Z."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
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
