"""Standard response envelope helpers."""

import random
import string
from flask import jsonify

import db


def _gen_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta(extra: dict | None = None) -> dict:
    m = {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": db.iso_now(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def no_content():
    # 204 No Content — no body at all
    return ("", 204)


def list_ok(items, limit: int, offset: int, total_count: int, status: int = 200):
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": (offset + limit) < total_count,
            }
        ),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
