"""Response envelope helpers — emits the exact structure described in
SCAFFOLD §1.0 and PRD §2.2."""

from __future__ import annotations

import datetime as _dt
import secrets
import string


def _now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits, ending in Z."""
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def make_meta(extra: dict | None = None) -> dict:
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(data: dict | None) -> dict:
    return {
        "meta": make_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }


def success_array(items: list, limit: int, offset: int, total_count: int) -> dict:
    has_more = (offset + len(items)) < total_count
    return {
        "meta": make_meta(
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


def error_response(error_id: str, message: str) -> dict:
    return {
        "meta": make_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
