"""Response envelope helpers (PRD §2.2).

Success envelope:
  { "meta": { "api_request_id", "api_request_timestamp", [pagination] },
    "response_type": "object" | "array", "data": ... }

Error envelope:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id", "message" } }
"""
from __future__ import annotations

import secrets
import string
from typing import Any

from flask import jsonify

from clock import now_iso


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return "req_" + suffix


def _meta(pagination: dict | None = None) -> dict:
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data: Any, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_ok(items: list, limit: int, offset: int, total_count: int):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": _meta(pagination=pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(error_id: str, http_status: int, message: str | None = None):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status
