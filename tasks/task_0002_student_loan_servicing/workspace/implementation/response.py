"""Response envelope helpers per PRD §2.2."""
from __future__ import annotations

import random
import string
from datetime import datetime, timezone
from typing import Any

from flask import jsonify


def _now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    now = datetime.now(timezone.utc)
    # millisecond precision
    ms = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def _gen_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    rnd = "".join(random.choice(alphabet) for _ in range(20))
    return f"req_{rnd}"


def _meta_base() -> dict:
    return {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": _now_iso(),
    }


def success(data: Any, status: int = 200):
    """Single-object success response."""
    body = {
        "meta": _meta_base(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items: list, limit: int, offset: int, total_count: int, status: int = 200):
    """List/array success response with pagination metadata in meta."""
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
