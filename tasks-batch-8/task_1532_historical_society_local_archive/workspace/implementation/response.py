"""Standard response envelope helpers per PRD §2.2 / §2.3 and scaffold §1.0."""

from __future__ import annotations

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def _request_ts() -> str:
    """Wall-clock receipt timestamp for the meta block (ISO 8601 UTC, 3dp)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_ts(),
    }


def convert_json(value):
    """Recursively convert Decimals to int/float for JSON serialization."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {k: convert_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [convert_json(v) for v in value]
    return value


def success_object(data: dict, http_status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": convert_json(data),
    }
    return jsonify(body), http_status


def success_list(items: list, limit: int, offset: int, total_count: int, http_status: int = 200):
    page = convert_json(items)
    meta = _meta()
    meta.update(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(page)) < total_count,
        }
    )
    body = {
        "meta": meta,
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), http_status


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
