"""Response envelope per PRD §2.2 / scaffold response_envelope.

Success object:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601",
              [optional pagination fields...] },
    "response_type": "object" | "array",
    "data": { ... } }

Error:
  { "meta": { ... },
    "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }

Pagination params (list endpoints): limit, offset, total_count, has_more.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from flask import Flask, g, request

from .store import store
from .util import format_iso8601, new_request_id

PAGINATION_DEFAULTS = {"limit": 10, "min": 1, "max": 100, "offset": 0}


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
    def _start_request() -> None:
        g.api_request_id = new_request_id()
        g.api_request_timestamp = format_iso8601(datetime.now(tz=timezone.utc))
        # Serialize requests on the global store lock so multi-threaded servers
        # observe deterministic first-writer-wins semantics for races described in §2.10.
        lock = store().lock
        lock.acquire()
        g._store_lock = lock

    @app.teardown_request
    def _end_request(_exc) -> None:
        lock = getattr(g, "_store_lock", None)
        if lock is not None:
            try:
                lock.release()
            except RuntimeError:
                pass
            g._store_lock = None


def parse_pagination() -> tuple[int, int]:
    """Read & validate limit/offset query-string params."""
    from .errors import APIError

    raw_limit = request.args.get("limit", default=None)
    raw_offset = request.args.get("offset", default=None)

    try:
        limit = int(raw_limit) if raw_limit is not None else PAGINATION_DEFAULTS["limit"]
    except (TypeError, ValueError):
        raise APIError("ERR_INVALID_INPUT", "limit must be an integer", 422)

    try:
        offset = int(raw_offset) if raw_offset is not None else PAGINATION_DEFAULTS["offset"]
    except (TypeError, ValueError):
        raise APIError("ERR_INVALID_INPUT", "offset must be an integer", 422)

    if limit < PAGINATION_DEFAULTS["min"] or limit > PAGINATION_DEFAULTS["max"]:
        raise APIError(
            "ERR_INVALID_INPUT",
            f"limit must be in [{PAGINATION_DEFAULTS['min']},{PAGINATION_DEFAULTS['max']}]",
            422,
        )
    if offset < 0:
        raise APIError("ERR_INVALID_INPUT", "offset must be >= 0", 422)
    return limit, offset


def paginate(items: List[Any], limit: int, offset: int) -> List[Any]:
    return items[offset : offset + limit]
