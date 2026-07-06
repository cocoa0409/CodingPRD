"""Standard response envelope helpers."""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify


def _fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC with 3 fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def _request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta_wall() -> dict:
    """Meta uses wall-clock request timestamp (server-generated, not logical clock)."""
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _fmt_ts(datetime.now(timezone.utc)),
    }


def success(data, http_status: int = 200, response_type: str = "object", pagination: dict | None = None):
    meta = _meta_wall()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), http_status


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta_wall(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status


def paginate(items: list, limit: int, offset: int) -> tuple[list, dict]:
    total = len(items)
    window = items[offset : offset + limit]
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
