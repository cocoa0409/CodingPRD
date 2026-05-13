from __future__ import annotations

"""Standard response envelope helpers."""

import secrets
import string
from typing import Any

from flask import jsonify

from clock import iso


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _meta(pagination: dict | None = None) -> dict:
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def success_object(data: Any, http_status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def success_array(items: list, *, limit: int, offset: int, total_count: int, http_status: int = 200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def success_empty(http_status: int = 204):
    # 204 No Content per HTTP spec carries no body; envelope only used otherwise.
    if http_status == 204:
        return ("", 204)
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": {},
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
