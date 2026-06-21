"""Standard response-envelope helpers (PRD §2.2).

Success envelope:
  { "meta": {api_request_id, api_request_timestamp [, pagination]},
    "response_type": "object"|"array", "data": ... }
Error envelope:
  { "meta": {api_request_id, api_request_timestamp},
    "response_type": "error", "data": {error_id, message} }
"""
from __future__ import annotations

from typing import Any, Optional
from flask import jsonify

from db import new_request_id, now_iso


def _meta(extra: Optional[dict] = None) -> dict:
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data: Any, http_status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_status


def ok_array(items: list, limit: int, offset: int, total_count: int, http_status: int = 200):
    # has_more is true when items beyond this page remain (PRD §2.3).
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
