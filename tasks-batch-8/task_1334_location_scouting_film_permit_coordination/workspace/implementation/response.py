"""Response envelope helpers matching SCAFFOLD.yaml §1.0 / PRD §2.2."""

import random
import string
from flask import jsonify
from db import store


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def _timestamp() -> str:
    return store.clock.now_iso()


def success_object(data: dict, status_code: int = 200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _timestamp(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status_code


def success_list(items: list, limit: int, offset: int, total_count: int):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
