"""Standard response envelope helpers (per PRD §2.2 and scaffold response_envelope)."""

import random
import string

from flask import g, jsonify

from clock import clock


def _new_request_id() -> str:
    chars = string.ascii_letters + string.digits
    rand = "".join(random.choices(chars, k=20))
    return f"req_{rand}"


def init_request():
    g.api_request_id = _new_request_id()
    g.api_request_timestamp = clock.now_iso()


def _meta_base():
    return {
        "api_request_id": getattr(g, "api_request_id", None) or _new_request_id(),
        "api_request_timestamp": getattr(g, "api_request_timestamp", None) or clock.now_iso(),
    }


def success(data, status_code: int = 200):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta_base(),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status_code


def paginated(items, limit: int, offset: int, total_count: int, status_code: int = 200):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status_code


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
