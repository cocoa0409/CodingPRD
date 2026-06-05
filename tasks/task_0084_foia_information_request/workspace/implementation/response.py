"""Standard response envelope helpers (PRD §2.2)."""

import secrets
import string
from typing import Any, Optional

from flask import jsonify

from clock import now_iso


def _new_request_id() -> str:
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta(extras: Optional[dict] = None) -> dict:
    m = {
        "api_request_id": _new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extras:
        m.update(extras)
    return m


def ok_object(data: Any, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_array(items: list, *, limit: int, offset: int, total_count: int, has_more: bool, status: int = 200):
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
    resp = jsonify(body)
    resp.status_code = status
    return resp


def err(error_id: str, message: str, status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
