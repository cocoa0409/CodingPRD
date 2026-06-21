"""Standard response-envelope helpers per PRD §2.2."""

from __future__ import annotations

import random
import string
from datetime import datetime, timezone
from typing import Any

from flask import jsonify


def _now_iso_ms() -> str:
    """ISO 8601 UTC timestamp with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    now = datetime.now(timezone.utc)
    # Format with milliseconds (3 fractional digits).
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _request_id() -> str:
    """Generate a server request id beginning with `req_`."""
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(alphabet, k=20))
    return f"req_{suffix}"


def _meta_base() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso_ms(),
    }


def success_object(data: Any, status: int = 200):
    body = {
        "meta": _meta_base(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_array(
    data: list,
    *,
    limit: int,
    offset: int,
    total_count: int,
    status: int = 200,
):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(data)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id: str, http_status: int, message: str = ""):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status
