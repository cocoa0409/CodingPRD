"""Standard response envelope helpers (per SCAFFOLD §1.0 and PRD §2.2)."""

import random
import string

from flask import jsonify

import db


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.iso_timestamp(),
    }


def success_object(data: dict, http_status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def success_list(items: list, total_count: int, limit: int, offset: int, http_status: int = 200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
