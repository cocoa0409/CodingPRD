"""Response envelope helpers."""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify


def _alnum(n: int) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def gen_request_id() -> str:
    # "req_" + 20 alphanumeric characters
    return "req_" + _alnum(20)


def utc_now_iso() -> str:
    """ISO 8601 UTC with milliseconds and Z suffix.

    Uses the platform clock (PRD §2.10) so that responses are coherent with
    the timestamps stored on entities (which also use the platform clock).
    Falls back to wall clock if the clock module is unavailable.
    """
    try:
        from clock import clock
        now = clock.now()
    except Exception:
        now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def iso_format(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def make_meta(pagination: dict | None = None) -> dict:
    meta = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": utc_now_iso(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def success(data, status: int = 200, response_type: str = "object", pagination: dict | None = None):
    body = {
        "meta": make_meta(pagination=pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def list_response(items: list, total: int, limit: int, offset: int, status: int = 200):
    has_more = (offset + len(items)) < total
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return success(items, status=status, response_type="array", pagination=pagination)


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def no_content(status: int = 204):
    """Return an HTTP 204 response with empty body."""
    from flask import Response
    return Response(status=status)
