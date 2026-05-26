"""Standard response envelope helpers per PRD §2.2."""
import secrets
import string

from flask import jsonify

import clock


def _make_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _base_meta() -> dict:
    return {
        "api_request_id": _make_request_id(),
        "api_request_timestamp": clock.iso(clock.now()),
    }


def success_object(data: dict, status: int = 200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_array(items: list, limit: int, offset: int, total_count: int, status: int = 200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status
