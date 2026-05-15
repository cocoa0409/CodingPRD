"""Response envelope helpers."""
from __future__ import annotations

import secrets
from typing import Any, Optional

from flask import jsonify

from app.clock import clock


def _request_id() -> str:
    return "req_" + secrets.token_hex(10)


def build_meta(**extra: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    for key, value in extra.items():
        if value is not None:
            meta[key] = value
    return meta


def success_object(data: Any, status: int = 200, **meta_extra: Any):
    body = {
        "meta": build_meta(**meta_extra),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_array(
    data: list[Any],
    *,
    limit: int,
    offset: int,
    total_count: int,
    status: int = 200,
):
    has_more = offset + limit < total_count
    body = {
        "meta": build_meta(
            limit=limit,
            offset=offset,
            total_count=total_count,
            has_more=has_more,
        ),
        "response_type": "array",
        "data": data,
    }
    return jsonify(body), status


def empty_success(status: int = 200):
    return success_object({}, status=status)
