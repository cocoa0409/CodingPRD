"""Response envelope helpers."""

import secrets
import string
from flask import jsonify

import db


def _gen_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta(include_pagination: bool = False, limit=None, offset=None, total_count=None):
    m = {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": db.iso_now(),
    }
    if include_pagination:
        m["limit"] = limit
        m["offset"] = offset
        m["total_count"] = total_count
        m["has_more"] = (offset + limit) < total_count if (limit is not None and offset is not None and total_count is not None) else False
    return m


def success_object(data, status: int = 200):
    body = {
        "meta": _meta(False),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit: int, offset: int, total_count: int, status: int = 200):
    body = {
        "meta": _meta(True, limit=limit, offset=offset, total_count=total_count),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id: str, message: str, status: int):
    body = {
        "meta": _meta(False),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
