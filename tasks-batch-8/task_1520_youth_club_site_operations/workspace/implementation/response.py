"""Standard response envelope (PRD §2.2 / scaffold §1.0)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=22))
    return "req_" + suffix


def _request_timestamp():
    now = datetime.now(timezone.utc)
    ms = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S") + (".%03dZ" % ms)


def success(data, status=200, is_list=False, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {
        "meta": meta,
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(api_err):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": api_err.error_id,
            "message": api_err.message,
        },
    }
    return jsonify(body), api_err.http_status


def fallback_error(status, message):
    return error_response(ApiError("ERR_VALIDATION" if status == 400 else "ERR_NOT_FOUND",
                                   status, message))
