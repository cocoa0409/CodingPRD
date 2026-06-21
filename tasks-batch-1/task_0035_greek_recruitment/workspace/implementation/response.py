from __future__ import annotations

"""Standard response envelope helpers."""
from typing import Any

from flask import jsonify

import db


def _meta(extra: dict | None = None) -> dict:
    meta = {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.format_ts(db.now_utc()),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(data: Any, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_array(items: list, *, limit: int, offset: int, total_count: int, status: int = 200):
    has_more = (offset + limit) < total_count
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": items,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id: str, message: str, status: int):
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
