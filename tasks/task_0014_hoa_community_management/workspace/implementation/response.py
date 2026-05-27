"""Response envelope helpers — follows PRD §2.2 envelope structure."""
from __future__ import annotations

import datetime
import secrets
import string


def _request_id() -> str:
    alpha = string.ascii_uppercase + string.digits
    body = "".join(secrets.choice(alpha) for _ in range(20))
    return f"req_{body}"


def _now_iso8601() -> str:
    # ISO 8601 UTC with three fractional digits (per PRD §2.2)
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success(data, status: int = 200, response_type: str = "object",
            pagination: dict | None = None):
    """Wrap a success response in the standard envelope."""
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso8601(),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return body, status


def list_success(items, total_count: int, limit: int, offset: int,
                 status: int = 200):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, status=status, response_type="array",
                   pagination=pagination)


def error(error_id: str, message: str, status: int):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso8601(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return body, status
