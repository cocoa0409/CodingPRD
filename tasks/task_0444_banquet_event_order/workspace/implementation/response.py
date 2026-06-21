"""Standard response envelope helpers (PRD §2.2 / §1.0).

Success object:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": ISO8601,
              [pagination fields for lists] },
    "response_type": "object" | "array", "data": {...} }

Error:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id": "...", "message": "..." } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _timestamp():
    # ISO 8601 UTC with exactly three fractional digits, e.g. 2025-05-24T10:30:00.123Z
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(pagination=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def list_success(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, status=200, response_type="array", pagination=pagination)


def error(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    resp = jsonify(body)
    resp.status_code = api_error.http_status
    return resp
