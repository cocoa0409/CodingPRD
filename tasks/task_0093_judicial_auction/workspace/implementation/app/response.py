"""Response envelope helpers per PRD §2.2."""
from __future__ import annotations

import random
import string
from typing import Any

from .clock import now_iso_ms


def make_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(alphabet, k=20))
    return f"req_{suffix}"


def _meta_basic() -> dict[str, Any]:
    return {
        "api_request_id": make_request_id(),
        "api_request_timestamp": now_iso_ms(),
    }


def success_envelope(
    data: Any,
    response_type: str = "object",
    pagination: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = _meta_basic()
    if pagination is not None:
        meta.update(pagination)
    return {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }


def error_envelope(error_id: str, message: str) -> dict[str, Any]:
    return {
        "meta": _meta_basic(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }


def paginate(items: list[Any], limit: int, offset: int) -> tuple[list[Any], dict[str, Any]]:
    total = len(items)
    sliced = items[offset : offset + limit]
    return sliced, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
