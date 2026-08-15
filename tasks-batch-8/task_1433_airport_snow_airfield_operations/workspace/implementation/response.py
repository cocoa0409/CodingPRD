"""Response envelope helpers per PRD section 2.2."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_iso_ms() -> str:
    """ISO 8601 UTC with three fractional digits."""
    dt = datetime.now(timezone.utc)
    ms = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return ms


def _meta(include_pagination: bool = False, limit=None, offset=None,
          total_count=None, has_more=None) -> dict:
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso_ms(),
    }
    if include_pagination:
        m["limit"] = limit
        m["offset"] = offset
        m["total_count"] = total_count
        m["has_more"] = has_more
    return m


def success_object(data, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status: int = 200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta(True, limit, offset, total_count, has_more),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def success_array_no_pagination(items, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id: str, http_status: int, message: str):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
