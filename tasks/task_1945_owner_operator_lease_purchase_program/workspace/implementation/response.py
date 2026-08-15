"""Response envelope helpers (SCAFFOLD.yaml §1.0, PRD §2.2)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _wall_timestamp():
    now = datetime.now(timezone.utc)
    ms = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def success(data, response_type="object", http_status=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_timestamp(),
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
    return jsonify(body), http_status


def error(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
