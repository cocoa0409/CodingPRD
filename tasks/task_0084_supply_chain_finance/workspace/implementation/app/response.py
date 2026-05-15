"""Response envelope helpers (PRD §2.2 + §2.3).

Success envelope:
    {
      "meta": {
        "api_request_id": "req_<20alpha>",
        "api_request_timestamp": "<ISO8601 UTC, 3 fractional digits, Z suffix>",
        // for list endpoints: limit, offset, total_count, has_more
      },
      "response_type": "object" | "array",
      "data": ...
    }

Error envelope: response_type="error", data has error_id+message.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any

from flask import jsonify


_ALPHA = string.ascii_letters + string.digits


def _request_id() -> str:
    return "req_" + "".join(secrets.choice(_ALPHA) for _ in range(20))


def _now_ts() -> str:
    """ISO 8601 UTC, three fractional digits, Z suffix."""
    now = datetime.now(timezone.utc)
    ms = f"{now.microsecond // 1000:03d}"
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + ms + "Z"


def _base_meta() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_ts(),
    }


def success_envelope(
    data: Any,
    status: int = 200,
    response_type: str = "object",
    pagination: dict | None = None,
):
    meta = _base_meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_envelope(items: list, total: int, limit: int, offset: int, status: int = 200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return success_envelope(items, status=status, response_type="array", pagination=pagination)


def error_envelope(error_id: str, message: str, http_status: int):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
