"""Standard API response envelope helpers (PRD §2.2)."""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import jsonify

from clock import now_iso


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _meta() -> Dict[str, Any]:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }


def success_object(data: Any, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_array(data: list, *, limit: int, offset: int,
                  total_count: int, status: int = 200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
