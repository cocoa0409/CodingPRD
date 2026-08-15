"""Standard response envelope helpers."""
import secrets
import string
from flask import jsonify
from db import now_iso


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def success(data, status=200, is_list=False, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
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


def error(error_id, message, status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
