"""Response envelope helpers."""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify

from clock import current_clock


def _now_iso_real() -> str:
    """Real wall-clock timestamp for api_request_timestamp.

    The api_request_timestamp is the actual server time when the request was
    handled, not the simulated logical clock used for business transitions.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _gen_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{body}"


def meta_base() -> dict:
    return {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": _now_iso_real(),
    }


# Backwards-compatible alias (some modules import the private name).
_meta_base = meta_base


def success(data, status_code: int = 200, response_type: str = "object",
            pagination: dict | None = None):
    meta = meta_base()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status_code
    return resp


def list_response(items: list, limit: int, offset: int, total_count: int,
                  status_code: int = 200):
    has_more = (offset + limit) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, status_code=status_code, response_type="array",
                   pagination=pagination)


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
