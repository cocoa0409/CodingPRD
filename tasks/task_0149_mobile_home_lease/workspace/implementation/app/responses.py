"""Response envelope helpers and per-request hooks."""
from __future__ import annotations

from typing import Any, Optional

from flask import Flask, Response, g, jsonify, request

from .clock import clock
from .store import new_request_id


def _meta(extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    req_id = getattr(g, "api_request_id", None) or new_request_id()
    ts = getattr(g, "api_request_timestamp", None) or clock.iso_now()
    meta: dict[str, Any] = {
        "api_request_id": req_id,
        "api_request_timestamp": ts,
    }
    if extra:
        meta.update(extra)
    return meta


def success_response(
    data: Any,
    *,
    status: int = 200,
    response_type: str = "object",
    pagination: Optional[dict[str, Any]] = None,
) -> Response:
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def list_response(
    items: list[Any],
    *,
    limit: int,
    offset: int,
    total_count: int,
) -> Response:
    has_more = (offset + limit) < total_count
    return success_response(
        items,
        status=200,
        response_type="array",
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
    )


def error_response(error_id: str, message: str, http_status: int) -> Response:
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def register_request_hooks(app: Flask) -> None:
    @app.before_request
    def _set_request_context() -> None:
        g.api_request_id = new_request_id()
        g.api_request_timestamp = clock.iso_now()


__all__ = [
    "success_response",
    "list_response",
    "error_response",
    "register_request_hooks",
]
