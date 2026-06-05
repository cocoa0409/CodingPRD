"""Standard response envelope helpers (PRD §2.2)."""
from __future__ import annotations

from typing import Any, Optional

from flask import jsonify

import db


def _meta(pagination: Optional[dict] = None) -> dict:
    m = {
        "api_request_id": db.gen_request_id(),
        "api_request_timestamp": db.iso_format(db.now_utc()),
    }
    if pagination:
        m.update(pagination)
    return m


def success_object(data: Any, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_array(items: list, limit: int, offset: int, total_count: int, status: int = 200):
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
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id: str, message: str, http_status: int):
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
