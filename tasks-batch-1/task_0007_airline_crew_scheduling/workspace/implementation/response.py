"""Response envelope helpers per PRD §2.2."""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify


def _now_iso_ms() -> str:
    """ISO 8601 UTC timestamp with three fractional-second digits (PRD §2.2)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _request_id() -> str:
    """Generate a server-side request id prefixed with 'req_'."""
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _meta(extra: dict | None = None) -> dict:
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso_ms(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status: int = 200, response_type: str = "object"):
    body = {
        "meta": _meta(),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def paginated(data: list, limit: int, offset: int, total_count: int, status: int = 200):
    has_more = (offset + len(data)) < total_count
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
