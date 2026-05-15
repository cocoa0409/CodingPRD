"""Response envelope construction."""
from __future__ import annotations
from typing import Any

from flask import jsonify, request

from core.clock import clock
from core.ids import new_request_id


def _meta(pagination: dict | None = None) -> dict:
    # Allow callers to set a request id via header for test traceability; otherwise mint.
    req_id = getattr(request, "_api_request_id", None) or new_request_id()
    meta = {
        "api_request_id": req_id,
        "api_request_timestamp": clock.iso(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def success_object(data: Any, http_status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def success_array(items: list, limit: int, offset: int, total_count: int, http_status: int = 200):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": _meta(pagination),
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
