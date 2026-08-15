"""Response envelope helpers (PRD §2.2, SCAFFOLD §1.0).

Success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error", "data": {"error_id", "message"}}
Pagination fields in meta for list responses: limit, offset, total_count, has_more.
"""

import random
import string
from flask import jsonify

import db


def _request_id() -> str:
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta_base() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def success_object(data, http_code: int = 200):
    body = {
        "meta": _meta_base(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_code


def success_list(items, limit: int, offset: int, total_count: int, http_code: int = 200):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_code


def error_response(error_id: str, message: str, http_code: int):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_code
