"""Standard response envelope helpers (scaffold response_envelope)."""

import random
import string
from datetime import datetime, timezone


def make_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def envelope_timestamp():
    """ISO 8601 UTC with three fractional digits (real wall clock, format only)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": make_request_id(),
            "api_request_timestamp": envelope_timestamp(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return body, status


def success_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": make_request_id(),
            "api_request_timestamp": envelope_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return body, 200


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": make_request_id(),
            "api_request_timestamp": envelope_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return body, http_status
