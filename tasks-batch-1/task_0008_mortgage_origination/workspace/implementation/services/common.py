"""Shared helpers: common fields, pagination, request-body parsing/validation."""
from __future__ import annotations

from typing import Any

from flask import request

import db
from errors import ApiError, ERR_INVALID_REQUEST


# Monotonic counter to disambiguate ties when multiple entities are created in
# the same millisecond — used purely as a hidden tie-breaker in sorts.
_creation_seq = [0]


def _next_creation_seq() -> int:
    _creation_seq[0] += 1
    return _creation_seq[0]


# ---------- Common entity bookkeeping ----------
def new_common_fields(*, with_version: bool = True) -> dict[str, Any]:
    ts = db.fmt_ts(db.utcnow())
    base: dict[str, Any] = {
        "id": db.new_id(),
        "created_at": ts,
        "_seq": _next_creation_seq(),
    }
    # UDAAPCheck is the only entity with `common_fields: false` — it carries
    # only id + created_at. Everyone else gets updated_at and version.
    if with_version:
        base["updated_at"] = ts
        base["version"] = 1
    return base


def bump(entity: dict[str, Any]) -> None:
    """Bump updated_at + version on a non-UDAAP entity."""
    entity["updated_at"] = db.fmt_ts(db.utcnow())
    entity["version"] = entity.get("version", 0) + 1


# ---------- Request body parsing ----------
def get_json_body() -> dict[str, Any]:
    """Return the JSON request body as a dict (or {} on empty body).

    Reject non-object JSON or malformed JSON with ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, "Body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


def require_field(body: dict[str, Any], name: str) -> Any:
    if name not in body:
        raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return body[name]


def require_str(body: dict[str, Any], name: str, *, non_empty: bool = True) -> str:
    v = require_field(body, name)
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be a string.")
    if non_empty and not v.strip():
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be non-empty.")
    return v


def require_int(body: dict[str, Any], name: str) -> int:
    v = require_field(body, name)
    # Reject bool (Python: bool is subclass of int) and floats.
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be an integer.")
    return v


def require_int_range(body: dict[str, Any], name: str, *, low: int, high: int) -> int:
    v = require_int(body, name)
    if v < low or v > high:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be in [{low}, {high}].")
    return v


def require_enum(body: dict[str, Any], name: str, choices: set[str]) -> str:
    v = require_field(body, name)
    if not isinstance(v, str) or v not in choices:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Field {name} must be one of: {', '.join(sorted(choices))}.",
        )
    return v


# ---------- Pagination ----------
def parse_pagination() -> tuple[int, int]:
    """Read limit/offset from request.args; defaults 10/0, limit min=1, max=100."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, "limit must be in [1, 100].")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0.")

    return limit, offset


def paginate(items: list[Any], limit: int, offset: int) -> tuple[list[Any], int]:
    """Return (page, total_count). items must already be sorted by created_at ASC."""
    total = len(items)
    return items[offset : offset + limit], total


def sorted_by_created_at(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda x: (x.get("created_at", ""), x.get("_seq", 0), x.get("id", "")))
