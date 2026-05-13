"""Standard response envelope helpers."""

import secrets
import string
from typing import Any, Optional

from flask import jsonify

from clock import now_iso


def _request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta(pagination: Optional[dict] = None) -> dict:
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data: Any, status: int = 200, pagination: Optional[dict] = None):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def paginated(items: list, limit: int, offset: int, total: int, status: int = 200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return success(items, status=status, pagination=pagination)


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
