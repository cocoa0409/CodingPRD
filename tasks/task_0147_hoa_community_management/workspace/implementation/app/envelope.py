"""Response envelope construction.

Format defined in PRD §2.2 and SCAFFOLD.response_envelope:

  Success object:
    { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601",
                [optional pagination fields...] },
      "response_type": "object" | "array",
      "data": { ... } }

  Error:
    { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
      "response_type": "error",
      "data": { "error_id": "ERR_XXX", "message": "..." } }

  Pagination params (list endpoints): limit, offset, total_count, has_more.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import Flask, g, request

from .util import format_iso8601, new_request_id


def _meta() -> Dict[str, Any]:
    req_id = getattr(g, "api_request_id", None) or new_request_id()
    ts = getattr(g, "api_request_timestamp", None)
    if ts is None:
        ts = format_iso8601(datetime.now(tz=timezone.utc))
    return {"api_request_id": req_id, "api_request_timestamp": ts}


def success_object(data: Dict[str, Any]) -> Dict[str, Any]:
    return {"meta": _meta(), "response_type": "object", "data": data}


def success_array(
    data: List[Dict[str, Any]],
    *,
    limit: int,
    offset: int,
    total_count: int,
) -> Dict[str, Any]:
    has_more = (offset + len(data)) < total_count
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = has_more
    return {"meta": meta, "response_type": "array", "data": data}


def empty_success() -> Dict[str, Any]:
    return {"meta": _meta(), "response_type": "object", "data": {}}


def error_envelope(error_id: str, message: str) -> Dict[str, Any]:
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def register_request_lifecycle(app: Flask) -> None:
    @app.before_request
    def _start_request() -> None:  # noqa: D401
        # Stamp every request with an id and a timestamp at receipt.
        g.api_request_id = new_request_id()
        g.api_request_timestamp = format_iso8601(datetime.now(tz=timezone.utc))


# ---------- Pagination helper ----------


PAGINATION_DEFAULTS = {"limit": 10, "min": 1, "max": 100, "offset": 0}


def parse_pagination() -> tuple[int, int]:
    """Read & validate limit/offset query-string params. Raises APIError on bad values."""
    from .errors import APIError  # local import to avoid cycle

    raw_limit = request.args.get("limit", default=None)
    raw_offset = request.args.get("offset", default=None)

    try:
        limit = int(raw_limit) if raw_limit is not None else PAGINATION_DEFAULTS["limit"]
    except (TypeError, ValueError):
        raise APIError("ERR_INVALID_STATE", "limit must be an integer", 409)

    try:
        offset = int(raw_offset) if raw_offset is not None else PAGINATION_DEFAULTS["offset"]
    except (TypeError, ValueError):
        raise APIError("ERR_INVALID_STATE", "offset must be an integer", 409)

    if limit < PAGINATION_DEFAULTS["min"] or limit > PAGINATION_DEFAULTS["max"]:
        raise APIError(
            "ERR_INVALID_STATE",
            f"limit must be in [{PAGINATION_DEFAULTS['min']},{PAGINATION_DEFAULTS['max']}]",
            409,
        )
    if offset < 0:
        raise APIError("ERR_INVALID_STATE", "offset must be >= 0", 409)
    return limit, offset


def paginate(items: List[Any], limit: int, offset: int) -> List[Any]:
    return items[offset : offset + limit]
