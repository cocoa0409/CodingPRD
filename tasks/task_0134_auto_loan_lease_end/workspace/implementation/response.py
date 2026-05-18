"""Response envelope builders — matches SCAFFOLD §1.0 and PRD §2.2 exactly.

Success envelope:
  { "meta": {...}, "response_type": "object" | "array", "data": ... }

Error envelope:
  { "meta": {...}, "response_type": "error",
    "data": { "error_id": "...", "message": "..." } }

Pagination fields ("limit", "offset", "total_count", "has_more") live inside
meta on list responses only.
"""
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
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


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
