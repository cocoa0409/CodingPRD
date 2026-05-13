"""Standard response envelope helpers.

Per PRD §2.2:
    - Success: {meta:{api_request_id, api_request_timestamp[, pagination]},
                response_type: 'object'|'array', data}
    - Error  : {meta:{api_request_id, api_request_timestamp},
                response_type: 'error',
                data: {error_id, message}}

ISO 8601 UTC timestamp with three fractional digits.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import jsonify


_ALPHABET = string.ascii_letters + string.digits


def make_request_id() -> str:
    """Server-generated unique request id with prefix 'req_'."""
    suffix = "".join(secrets.choice(_ALPHABET) for _ in range(20))
    return f"req_{suffix}"


def iso8601_now() -> str:
    """ISO 8601 UTC timestamp with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    now = datetime.now(timezone.utc)
    # Truncate microseconds to milliseconds (3 fractional digits).
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _base_meta() -> Dict[str, Any]:
    return {
        "api_request_id": make_request_id(),
        "api_request_timestamp": iso8601_now(),
    }


def success(data: Any, *, status: int = 200, response_type: str = "object"):
    body = {
        "meta": _base_meta(),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def success_object(data: Dict[str, Any], status: int = 200):
    return success(data, status=status, response_type="object")


def success_list(items: List[Any], *, limit: int, offset: int, total_count: int, status: int = 200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(items) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
