"""Response envelope helpers per PRD §2.2."""
from __future__ import annotations

import secrets
import string
from typing import Any, Iterable

from flask import jsonify

from .clock import now_iso


def _request_id() -> str:
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta_base() -> dict[str, Any]:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }


def success_envelope(data: Any, *, response_type: str = "object") -> dict[str, Any]:
    return {
        "meta": _meta_base(),
        "response_type": response_type,
        "data": data,
    }


def list_envelope(
    items: list[Any],
    *,
    total_count: int,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }


def error_envelope(error_id: str, message: str) -> dict[str, Any]:
    return {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }


def ok(data: Any, status: int = 200):
    return jsonify(success_envelope(data, response_type="object")), status


def created(data: Any):
    return jsonify(success_envelope(data, response_type="object")), 201


def listing(items: Iterable[Any], total_count: int, limit: int, offset: int):
    return (
        jsonify(list_envelope(list(items), total_count=total_count, limit=limit, offset=offset)),
        200,
    )
