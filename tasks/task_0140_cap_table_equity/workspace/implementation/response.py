"""Standard response envelope helpers. PRD §2.2."""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any, Optional

from flask import jsonify


_ALPHANUM = string.ascii_uppercase + string.ascii_lowercase + string.digits


def _new_request_id() -> str:
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def _iso_now_ms() -> str:
    """ISO 8601 UTC with three fractional digits + 'Z'."""
    dt = datetime.now(tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def make_meta(
    *,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> dict:
    meta = {
        "api_request_id": _new_request_id(),
        "api_request_timestamp": _iso_now_ms(),
    }
    if limit is not None:
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total_count
        meta["has_more"] = has_more
    return meta


def success(data: Any, http_status: int = 200):
    body = {
        "meta": make_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def created(data: Any):
    return success(data, http_status=201)


def list_response(
    items: list,
    *,
    limit: int,
    offset: int,
    total_count: int,
):
    body = {
        "meta": make_meta(
            limit=limit,
            offset=offset,
            total_count=total_count,
            has_more=(offset + len(items)) < total_count,
        ),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(error_id: str, message: str, http_status: int):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
