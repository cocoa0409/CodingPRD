"""Response envelope formatting."""

from __future__ import annotations

from typing import Any

from flask import jsonify, request

from clock import CLOCK
from errors import APIError
from ids import new_request_id


def _meta_base() -> dict[str, Any]:
    return {
        "api_request_id": getattr(request, "api_request_id", new_request_id()),
        "api_request_timestamp": CLOCK.now_iso(),
    }


def success(data: Any, status: int = 200, response_type: str = "object",
            limit: int | None = None, offset: int | None = None,
            total_count: int | None = None, has_more: bool | None = None):
    meta = _meta_base()
    if limit is not None:
        meta["limit"] = limit
    if offset is not None:
        meta["offset"] = offset
    if total_count is not None:
        meta["total_count"] = total_count
    if has_more is not None:
        meta["has_more"] = has_more

    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def list_success(items: list, limit: int, offset: int, total: int, status: int = 200):
    has_more = (offset + len(items)) < total
    return success(items, status=status, response_type="array",
                   limit=limit, offset=offset, total_count=total, has_more=has_more)


def error_response(err: APIError):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.status
    return resp
