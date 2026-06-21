"""Standard response envelope (PRD §2.2).

success:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": ISO8601, [pagination] },
    "response_type": "object" | "array", "data": {} }
error:
  { "meta": { api_request_id, api_request_timestamp },
    "response_type": "error", "data": { "error_id", "message" } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _now_iso_millis():
    # ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.2/§2.4).
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _request_id():
    # api_request_id starts with "req_" (PRD §2.2).
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


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
    return jsonify(body), status


def list_success(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, status=200, response_type="array", pagination=pagination)


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
