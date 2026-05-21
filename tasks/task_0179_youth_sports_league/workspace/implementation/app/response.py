"""Standard response envelope helpers."""
from __future__ import annotations

import secrets
from typing import Any

from flask import jsonify

from .time_utils import now_iso


def _new_request_id() -> str:
    # 20-char base alphabet — uppercase letters + digits — matching the PRD example shape req_RANDOMALPHANUM123456.
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def build_meta(pagination: dict | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "api_request_id": _new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success_response(
    data: Any,
    status_code: int = 200,
    *,
    response_type: str = "object",
    pagination: dict | None = None,
):
    body = {
        "meta": build_meta(pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status_code
    return resp


def error_response(error_id: str, message: str, status_code: int):
    body = {
        "meta": build_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = status_code
    return resp


def paginated_response(items: list, total: int, limit: int, offset: int):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return success_response(items, status_code=200, response_type="array", pagination=pagination)
