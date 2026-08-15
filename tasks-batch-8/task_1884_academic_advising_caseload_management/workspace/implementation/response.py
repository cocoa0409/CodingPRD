"""Standard response envelope helpers per scaffold response_envelope and PRD §2.2."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=22))


def _request_timestamp():
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(include_pagination=False, limit=None, offset=None, total_count=None, has_more=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if include_pagination:
        m["limit"] = limit
        m["offset"] = offset
        m["total_count"] = total_count
        m["has_more"] = has_more
    return m


def success_object(data, status_code=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status_code


def success_list(items, limit, offset, total_count, status_code=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta(True, limit, offset, total_count, has_more),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status_code


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
