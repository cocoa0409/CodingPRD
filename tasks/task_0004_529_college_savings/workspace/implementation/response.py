"""Standard response envelope helpers.

PRD §2.2: every response carries {"meta": {api_request_id, api_request_timestamp,
[pagination fields]}, "response_type": "object"|"array"|"error", "data": ...}.
Timestamps are ISO 8601 UTC with three fractional digits.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify


_REQ_ID_ALPHABET = string.ascii_uppercase + string.digits


def _make_request_id() -> str:
    suffix = "".join(secrets.choice(_REQ_ID_ALPHABET) for _ in range(20))
    return f"req_{suffix}"


def now_iso_ms() -> str:
    """Return current wall-clock time in ISO 8601 UTC with millisecond precision (Z-suffix)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _base_meta() -> Dict[str, Any]:
    return {
        "api_request_id": _make_request_id(),
        "api_request_timestamp": now_iso_ms(),
    }


def success_object(data: Dict[str, Any], status: int = 200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_array(
    data: List[Dict[str, Any]],
    *,
    limit: int,
    offset: int,
    total_count: int,
    status: int = 200,
):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(data)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id: str, message: str, status: int):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Pagination parsing
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination(args) -> Tuple[int, int]:
    """Read limit/offset from a flask request.args mapping.

    Raises ApiError(ERR_INVALID_REQUEST) when values are non-integer or out of range.
    """
    from errors import err, ERR_INVALID_REQUEST

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")

    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err(
                ERR_INVALID_REQUEST,
                f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}",
            )

    if raw_offset is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be non-negative")

    return limit, offset


def paginate(items: List[Dict[str, Any]], limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int]:
    """Slice items by (limit, offset). Returns (page, total_count)."""
    total = len(items)
    return items[offset : offset + limit], total
