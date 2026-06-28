"""Standard response envelope helpers.

Success envelope (verbatim from PRD §2.2 / scaffold §1.0):
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601" },
    "response_type": "object" | "array", "data": {} }

Error envelope:
  { "meta": { ... }, "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }

For list endpoints, meta additionally carries limit/offset/total_count/has_more.
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _request_timestamp():
    # api_request_timestamp is server-generated wall-clock ISO 8601 UTC with three
    # fractional digits. This is the response-envelope timestamp, distinct from the
    # logical clock used for business rules.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
