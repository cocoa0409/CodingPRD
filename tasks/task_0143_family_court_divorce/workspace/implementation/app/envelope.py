"""Response envelope helpers.

Implements the success and error response shape defined in PRD §2.2:

    {
      "meta": {
        "api_request_id": "req_<alnum>",
        "api_request_timestamp": "ISO8601 with .fffZ",
        # for list endpoints only:
        "limit": <int>, "offset": <int>, "total_count": <int>, "has_more": <bool>
      },
      "response_type": "object" | "array" | "error",
      "data": ...
    }
"""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify


_ALNUM = string.ascii_uppercase + string.ascii_lowercase + string.digits


def _make_request_id() -> str:
    rand = "".join(secrets.choice(_ALNUM) for _ in range(20))
    return f"req_{rand}"


def _now_iso() -> str:
    # ISO 8601 UTC with three fractional digits and a trailing Z.
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _base_meta() -> dict:
    return {
        "api_request_id": _make_request_id(),
        "api_request_timestamp": _now_iso(),
    }


def success(data, status: int = 200):
    """Single-resource success envelope (response_type='object')."""
    if data is None:
        data = {}
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_list(items, limit: int, offset: int, total_count: int, status: int = 200):
    """List success envelope (response_type='array') with pagination metadata."""
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id: str, message: str, status: int):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
