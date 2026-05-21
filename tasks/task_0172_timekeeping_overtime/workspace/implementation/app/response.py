"""Response envelope helpers — strict to the scaffold's response_envelope shape.

success:  { "meta": {...}, "response_type": "object"|"array", "data": {} }
error:    { "meta": {...}, "response_type": "error", "data": {error_id, message} }
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any, Dict, List


def _now_iso_ms() -> str:
    """ISO 8601 UTC timestamp with exactly three fractional digits and 'Z' suffix.

    Note: this is the wall-clock timestamp used for the response envelope's
    api_request_timestamp. It is NOT the logical server clock used for
    business-rule time-stamping (see app.clock for that)."""
    now = datetime.now(timezone.utc)
    ms = int(now.microsecond / 1000)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def _new_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _base_meta() -> Dict[str, Any]:
    return {
        "api_request_id": _new_request_id(),
        "api_request_timestamp": _now_iso_ms(),
    }


def make_object_envelope(data: Dict[str, Any] | None) -> Dict[str, Any]:
    return {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }


def make_array_envelope(
    items: List[Dict[str, Any]],
    *,
    limit: int,
    offset: int,
    total_count: int,
) -> Dict[str, Any]:
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }


def make_error_envelope(error_id: str, message: str) -> Dict[str, Any]:
    return {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
