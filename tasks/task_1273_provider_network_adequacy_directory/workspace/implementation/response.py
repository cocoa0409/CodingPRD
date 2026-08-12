"""Standard response envelope helpers, per scaffold §1.0 / PRD §2.2."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

import errors


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return f"req_{suffix}"


def _now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success_object(data, status_code: int = 200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status_code


def success_list(items, limit: int, offset: int, total_count: int, status_code: int = 200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status_code


def error_response(err: "errors.ApiError"):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status
