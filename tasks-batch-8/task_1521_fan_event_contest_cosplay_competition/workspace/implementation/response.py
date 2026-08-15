"""Standard response envelope (SCAFFOLD §1.0 / PRD §2.2)."""

import random
import string

from flask import jsonify

from db import now_ts


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=16))
    return "req_" + suffix


def success(data, status=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_ts(),
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


def error(error_id, message, status):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_ts(),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
