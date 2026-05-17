"""Response envelope helpers.

Matches the structure from SCAFFOLD §1.0 / PRD §2.2 exactly:
{
  "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601", ... },
  "response_type": "object" | "array" | "error",
  "data": { ... }
}
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any

from flask import jsonify


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _utc_now_iso_ms() -> str:
    """ISO 8601 UTC timestamp with exactly three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    now = datetime.now(timezone.utc)
    ms = int(now.microsecond / 1000)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def _meta_base() -> dict[str, Any]:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _utc_now_iso_ms(),
    }


def success(data: Any, status: int = 200):
    """Return a single-resource ('object') success response."""
    body = {
        "meta": _meta_base(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_success(items: list, *, limit: int, offset: int, total_count: int, status: int = 200):
    """Return a paginated list ('array') success response."""
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
