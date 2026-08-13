"""Standard response envelope helpers per scaffold §1.0 / PRD §2.2."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    rand = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + rand


def _request_timestamp():
    # Wall-clock request timestamp with three fractional digits (meta only;
    # business timestamps read the logical clock).
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success(data, response_type="object", status=200, pagination=None):
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
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
