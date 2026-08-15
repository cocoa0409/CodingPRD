"""Standard response envelope helpers (scaffold §1.0 / PRD §2.2)."""
from __future__ import annotations

from flask import jsonify

from db import CLOCK, new_request_id


def _meta(pagination: dict | None = None) -> dict:
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": CLOCK.now_str(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success_object(data: dict, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items: list, limit: int, offset: int, total_count: int, status: int = 200):
    has_more = (offset + len(items)) < total_count
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
    return jsonify(body), status


def error_response(error_id: str, message: str, status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
