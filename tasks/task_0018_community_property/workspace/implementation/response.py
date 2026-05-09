"""Response envelope helpers — produce the exact shape mandated by PRD §2.2.

Success body:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
              "limit": ..., "offset": ..., "total_count": ..., "has_more": ... },
    "response_type": "object" | "array",
    "data": ... }

Error body:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601" },
    "response_type": "error",
    "data": { "error_id": "...", "message": "..." } }
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any

from flask import jsonify, make_response


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _now_iso() -> str:
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success(data: Any, status: int = 200):
    """Single-resource (or empty-object) success response."""
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return make_response(jsonify(body), status)


def success_list(items: list, limit: int, offset: int, total_count: int, status: int = 200):
    """List/array success response with pagination meta."""
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return make_response(jsonify(body), status)


def error(error_id: str, message: str, http_status: int):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return make_response(jsonify(body), http_status)
