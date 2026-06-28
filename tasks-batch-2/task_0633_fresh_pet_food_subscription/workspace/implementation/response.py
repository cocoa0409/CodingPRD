"""Standard response envelope per PRD §2.2.

Success:
  { "meta": { "api_request_id", "api_request_timestamp", [pagination...] },
    "response_type": "object" | "array", "data": {} }
Error:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error", "data": { "error_id", "message" } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _now_iso_millis():
    # api_request_timestamp: server wall-clock, ISO 8601 UTC with three fractional digits.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alnum, k=20))


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


def list_success(items, limit, offset, total_count, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, status=status, response_type="array", pagination=pagination)


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
