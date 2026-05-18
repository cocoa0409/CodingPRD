"""Standard response envelope builders per PRD §2.2."""
from __future__ import annotations

from flask import jsonify

from db import store
from utils import iso_now, new_request_id


def _meta(extra: dict | None = None) -> dict:
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_now(store.now()),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_success(items, limit: int, offset: int, total_count: int, status: int = 200):
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
    return jsonify(body), status


def empty_success(status: int = 204):
    """204 No Content — emit no body (Flask convention)."""
    # 204 should not have a body per HTTP spec.
    return ("", status)


def error(error_id: str, message: str, status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
