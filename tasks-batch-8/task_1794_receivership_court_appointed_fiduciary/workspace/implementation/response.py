"""Response envelope helpers (PRD §2.2 / SCAFFOLD §1.0).

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination...]},
          "response_type": "object"|"array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _request_timestamp():
    """ISO 8601 UTC with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(api_error):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": api_error.error_id,
            "message": api_error.message,
        },
    }
    return jsonify(body), api_error.http_status
