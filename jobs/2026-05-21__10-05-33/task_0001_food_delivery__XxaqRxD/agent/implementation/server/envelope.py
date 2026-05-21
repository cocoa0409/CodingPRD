from __future__ import annotations

from typing import Any, Mapping

from flask import jsonify

from .clock import LogicalClock
from .ids import new_request_id


def _meta(clock: LogicalClock, extra: Mapping[str, Any] | None = None) -> dict:
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(clock: LogicalClock, data: Any, status: int = 200):
    body = {
        "meta": _meta(clock),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_list(
    clock: LogicalClock,
    data: list,
    *,
    limit: int,
    offset: int,
    total_count: int,
    status: int = 200,
):
    has_more = offset + len(data) < total_count
    body = {
        "meta": _meta(
            clock,
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            },
        ),
        "response_type": "array",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(clock: LogicalClock, error_id: str, message: str, status: int):
    body = {
        "meta": _meta(clock),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
