"""Standard response envelope helpers for the CECL Allowance API."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError


def make_request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def make_timestamp():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def success_response(body, status_code=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": make_request_id(),
        "api_request_timestamp": make_timestamp(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    envelope = {
        "meta": meta,
        "response_type": response_type,
        "data": body,
    }
    return jsonify(envelope), status_code


def error_response(error_id, message, http_status):
    meta = {
        "api_request_id": make_request_id(),
        "api_request_timestamp": make_timestamp(),
    }
    envelope = {
        "meta": meta,
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(envelope), http_status


def api_error_response(err):
    assert isinstance(err, ApiError)
    return error_response(err.error_id, err.message, err.http_status)
