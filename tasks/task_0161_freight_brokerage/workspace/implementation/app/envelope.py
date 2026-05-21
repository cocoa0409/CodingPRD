"""Response envelope helpers (PRD §2.2).

Successful responses:

    {
        "meta": {
            "api_request_id": "req_...",
            "api_request_timestamp": "...",
            [ "limit": N, "offset": N, "total_count": N, "has_more": bool ]
        },
        "response_type": "object" | "array",
        "data": {} | []
    }

Error responses set "response_type" to "error" and place
{"error_id": ..., "message": ...} into "data".
"""

from __future__ import annotations

import secrets
import string
from typing import Any, Iterable, Optional

from flask import jsonify

from .timeutil import iso_now


_ALPHABET = string.ascii_letters + string.digits


def new_request_id() -> str:
    """Generate a 'req_' prefixed alphanumeric request id."""
    rand = "".join(secrets.choice(_ALPHABET) for _ in range(20))
    return f"req_{rand}"


def build_meta(
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> dict:
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_now(),
    }
    if limit is not None:
        meta["limit"] = limit
    if offset is not None:
        meta["offset"] = offset
    if total_count is not None:
        meta["total_count"] = total_count
    if has_more is not None:
        meta["has_more"] = has_more
    return meta


def ok_object(data: Any, status: int = 200):
    body = {
        "meta": build_meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_array(
    data: Iterable[Any],
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
    status: int = 200,
):
    body = {
        "meta": build_meta(
            limit=limit, offset=offset, total_count=total_count, has_more=has_more
        ),
        "response_type": "array",
        "data": list(data),
    }
    return jsonify(body), status
