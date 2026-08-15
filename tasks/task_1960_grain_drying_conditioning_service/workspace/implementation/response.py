"""Standard response envelope helpers (PRD §2.2, §2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _request_timestamp():
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def success(data, code=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), code


def error_response(error_id, http_status, message):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
