"""Standard response envelope helpers per PRD §2.2 / §2.3."""

from __future__ import annotations

import random
import string

from flask import jsonify

import db


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def _request_ts() -> str:
    # PRD §2.4: all system-generated timestamps read the logical clock.
    return db.get_current_utc()


def success_object(data: dict, http_status: int = 200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_ts(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_status


def success_list(items: list, limit: int, offset: int, total_count: int, http_status: int = 200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_ts(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
