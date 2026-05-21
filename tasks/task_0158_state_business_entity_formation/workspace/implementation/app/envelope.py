"""Response envelope helpers (meta / response_type / data)."""
from __future__ import annotations

import secrets
import string
from typing import Any, Iterable

from flask import g

from .timeutil import iso, now


_ALPHABET = string.ascii_letters + string.digits


def _api_request_id() -> str:
    rid = getattr(g, "api_request_id", None)
    if rid is None:
        rid = "req_" + "".join(secrets.choice(_ALPHABET) for _ in range(20))
        try:
            g.api_request_id = rid
        except RuntimeError:
            # Outside of an active request context (shouldn't happen in normal flow).
            pass
    return rid


def _api_request_timestamp() -> str:
    ts = getattr(g, "api_request_timestamp", None)
    if ts is None:
        ts = iso(now())
        try:
            g.api_request_timestamp = ts
        except RuntimeError:
            pass
    return ts


def _base_meta() -> dict[str, Any]:
    return {
        "api_request_id": _api_request_id(),
        "api_request_timestamp": _api_request_timestamp(),
    }


def object_response(data: Any) -> dict[str, Any]:
    return {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }


def array_response(
    items: Iterable[Any],
    *,
    limit: int,
    offset: int,
    total_count: int,
) -> dict[str, Any]:
    items = list(items)
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }


def error_response(error_id: str, message: str) -> dict[str, Any]:
    return {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
