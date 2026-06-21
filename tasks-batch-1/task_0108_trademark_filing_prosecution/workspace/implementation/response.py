"""Standard response envelope helpers (PRD §2.2)."""

import secrets
import string
from flask import jsonify

from db import utcnow_iso


def _new_request_id() -> str:
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _meta(extra: dict = None) -> dict:
    m = {
        "api_request_id": _new_request_id(),
        "api_request_timestamp": utcnow_iso(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, http_status: int = 200):
    """Single-object (or empty) success response."""
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def list_success(items, limit: int, offset: int, total_count: int):
    """Array success response with pagination fields in meta (PRD §2.3)."""
    has_more = (offset + len(items)) < total_count
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(error_id: str, http_status: int, message: str = ""):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status
