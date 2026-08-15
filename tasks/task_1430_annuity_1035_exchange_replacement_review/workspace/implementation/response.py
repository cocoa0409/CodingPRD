"""Standard response envelope helpers (SCAFFOLD §1.0, PRD §2.2)."""
import random
import string
from flask import jsonify

import db


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=22))
    return f"req_{suffix}"


def success_object(data, status_code: int = 200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": db.now_formatted(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status_code


def success_list(items, limit: int, offset: int, total_count: int, status_code: int = 200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": db.now_formatted(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status_code


def error_response(error_id: str, message: str, status_code: int):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": db.now_formatted(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status_code
