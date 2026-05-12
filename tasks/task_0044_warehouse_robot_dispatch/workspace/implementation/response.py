"""Response envelope helpers."""
from __future__ import annotations

import random
import string
from datetime import datetime, timezone

from flask import jsonify, g


def _now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits."""
    now = datetime.now(timezone.utc)
    # Format with milliseconds
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _gen_request_id() -> str:
    """Generate api_request_id beginning with req_ and 20 alphanumeric chars."""
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _meta_base() -> dict:
    return {
        "api_request_id": getattr(g, "request_id", None) or _gen_request_id(),
        "api_request_timestamp": _now_iso(),
    }


def success(data, status: int = 200, response_type: str = "object", pagination: dict | None = None):
    meta = _meta_base()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def list_response(items, total: int, limit: int, offset: int, status: int = 200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return success(items, status=status, response_type="array", pagination=pagination)


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
