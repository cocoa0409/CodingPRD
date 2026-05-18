"""Response envelope helpers.

The envelope shape is fixed by §2.2 of the PRD:
- success:  { "meta": { api_request_id, api_request_timestamp, ... }, "response_type": "object"|"array", "data": {...|[]} }
- error:    { "meta": { api_request_id, api_request_timestamp }, "response_type": "error", "data": { error_id, message } }

Pagination fields (limit, offset, total_count, has_more) live INSIDE meta for list responses.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return f"req_{suffix}"


def _now_iso() -> str:
    """ISO 8601 UTC, three fractional digits, Z-suffixed."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def success_envelope(
    data: Any,
    *,
    is_array: bool = False,
    pagination: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if pagination is not None:
        # Pagination fields are merged into meta.
        for key in ("limit", "offset", "total_count", "has_more"):
            meta[key] = pagination[key]
    body: Dict[str, Any] = {
        "meta": meta,
        "response_type": "array" if is_array else "object",
        "data": data if data is not None else ({} if not is_array else []),
    }
    return body


def error_envelope(error_id: str, message: str) -> Dict[str, Any]:
    return {
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


def paginate(items: List[Any], limit: int, offset: int) -> Dict[str, Any]:
    total = len(items)
    page = items[offset : offset + limit]
    return {
        "page": page,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + limit < total,
        },
    }
