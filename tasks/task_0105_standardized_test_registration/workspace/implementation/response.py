"""Response envelope helpers — matches §2.2 of PRD exactly.

Success envelope:
    {
      "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
                "limit": ..., "offset": ..., "total_count": ..., "has_more": ... },
      "response_type": "object" | "array",
      "data": {...}
    }

Error envelope:
    {
      "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601" },
      "response_type": "error",
      "data": { "error_id": "...", "message": "..." }
    }
"""

import random
import string
from datetime import datetime, timezone
from typing import Any, Optional

from flask import jsonify


def _generate_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def _now_iso() -> str:
    n = datetime.now(timezone.utc)
    # ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _meta_base() -> dict:
    return {
        "api_request_id": _generate_request_id(),
        "api_request_timestamp": _now_iso(),
    }


def success(data: Any, status: int = 200):
    body = {
        "meta": _meta_base(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_list(items: list, limit: int, offset: int, total_count: int, status: int = 200):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def iso_utc_ms(dt: Optional[datetime]) -> Optional[str]:
    """Format a datetime as ISO 8601 UTC with millisecond precision."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso_utc(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp; raises ValueError on bad input."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    cleaned = s.strip()
    # Replace trailing Z with +00:00 for fromisoformat support.
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
