"""Response envelope helpers — strictly per PRD §2.2 and SCAFFOLD response_envelope.

Success envelope:
{
  "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601",
            optional pagination: limit, offset, total_count, has_more },
  "response_type": "object" | "array",
  "data": { ... } | [ ... ]
}

Error envelope:
{
  "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601" },
  "response_type": "error",
  "data": { "error_id": "ERR_X", "message": "..." }
}
"""
from __future__ import annotations

import datetime as _dt
import secrets
import string
from typing import Any, Iterable

from flask import Flask, g, request


# ------------------------- Request metadata helpers ------------------------- #

_ALPHANUM = string.ascii_uppercase + string.digits


def _generate_request_id() -> str:
    suffix = "".join(secrets.choice(_ALPHANUM) for _ in range(20))
    return f"req_{suffix}"


def _now_iso() -> str:
    # Wall-clock for response metadata only; not the logical clock.
    now = _dt.datetime.now(_dt.timezone.utc)
    # ISO 8601 UTC with milliseconds, 'Z' suffix.
    millis = f"{now.microsecond // 1000:03d}"
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + millis + "Z"


def register_request_hooks(app: Flask) -> None:
    @app.before_request
    def _populate_meta():
        g.api_request_id = _generate_request_id()
        g.api_request_timestamp = _now_iso()


def _meta_base() -> dict:
    return {
        "api_request_id": getattr(g, "api_request_id", _generate_request_id()),
        "api_request_timestamp": getattr(g, "api_request_timestamp", _now_iso()),
    }


# ------------------------- Envelope builders ------------------------- #

def build_success_envelope(data: Any, *, response_type: str = "object",
                           pagination: dict | None = None) -> dict:
    meta = _meta_base()
    if pagination is not None:
        meta.update(pagination)
    return {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }


def build_list_envelope(items: list, *, limit: int, offset: int, total_count: int) -> dict:
    has_more = (offset + limit) < total_count
    return build_success_envelope(
        items,
        response_type="array",
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
    )


def build_error_envelope(error_id: str, message: str) -> dict:
    return {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }


# ------------------------- Pagination parser ------------------------- #

def parse_pagination() -> tuple[int, int]:
    """Parse limit/offset from query string per PRD §2.3.

    limit default 10, min 1, max 100.
    offset default 0, must be non-negative integer.
    """
    from .errors import ApiError

    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_BAD_REQUEST", "limit and offset must be integers.")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_BAD_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_BAD_REQUEST", "offset must be a non-negative integer.")
    return limit, offset


def paginate(rows: Iterable[Any], limit: int, offset: int) -> tuple[list, int]:
    materialized = list(rows)
    total = len(materialized)
    return materialized[offset: offset + limit], total
