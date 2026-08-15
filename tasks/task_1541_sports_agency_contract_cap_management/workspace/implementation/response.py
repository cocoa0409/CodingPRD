"""Standard response envelope helpers (scaffold response_envelope, PRD 2.2).

Success:  { "meta": {api_request_id, api_request_timestamp[, limit, offset,
            total_count, has_more]}, "response_type": "object"|"array",
            "data": ... }
Error:    { "meta": {api_request_id, api_request_timestamp},
            "response_type": "error",
            "data": {"error_id": ..., "message": ...} }

api_request_timestamp is an ISO 8601 UTC timestamp with three fractional
digits. Per PRD 2.5 the server never falls back to wall-clock time, so the
logical clock is used.
"""

import random
import string

import db


def make_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def format_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def envelope_timestamp():
    return format_ts(db.get_clock())


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
