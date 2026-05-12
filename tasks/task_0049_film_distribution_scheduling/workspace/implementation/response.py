"""Standard response envelope helpers."""

import random
import string
from datetime import datetime, timezone
from flask import jsonify


def _now_iso():
    """ISO 8601 UTC timestamp with three fractional digits."""
    now = datetime.now(timezone.utc)
    # Format with milliseconds (three fractional digits)
    s = now.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{now.microsecond // 1000:03d}"
    return f"{s}.{millis}Z"


def _make_request_id():
    """req_ prefix + 20 alphanumeric chars."""
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=20))
    return f"req_{suffix}"


def success_object(data, http_status=200):
    body = {
        "meta": {
            "api_request_id": _make_request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def success_array(items, limit, offset, total_count, http_status=200):
    body = {
        "meta": {
            "api_request_id": _make_request_id(),
            "api_request_timestamp": _now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + limit) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(error_id: str, http_status: int, message: str = ""):
    body = {
        "meta": {
            "api_request_id": _make_request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status
