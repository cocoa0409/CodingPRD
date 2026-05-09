"""Standard response envelope helpers (per PRD §2.2 and scaffold §1.0)."""

from __future__ import annotations

import datetime as dt
import secrets
import string
from typing import Any, Iterable


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _now_iso_z() -> str:
    """ISO 8601 UTC with three fractional digits, ending in 'Z'."""
    now = dt.datetime.now(dt.timezone.utc)
    # millisecond precision, drop +00:00 with Z
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta_base() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso_z(),
    }


def success_response(data: Any) -> dict:
    """Single-resource success envelope."""
    return {
        "meta": _meta_base(),
        "response_type": "object",
        "data": data,
    }


def list_response(items: list, limit: int, offset: int, total_count: int) -> dict:
    """Paginated array envelope."""
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    return {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }


def error_response(error_id: str, message: str) -> dict:
    """Error envelope (4xx)."""
    return {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
