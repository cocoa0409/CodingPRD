"""Shared helpers: common-fields stamping, OCC, pagination, payload helpers."""
from __future__ import annotations

from typing import Any

from flask import request

from .clock import iso_format, now
from .errors import ApiError
from .store import gen_id


def stamp_new(entity: dict[str, Any], *, with_common: bool = True) -> dict[str, Any]:
    """Assign id and (optionally) created_at/updated_at/version."""
    entity.setdefault("id", gen_id())
    if with_common:
        ts = iso_format(now())
        entity.setdefault("created_at", ts)
        entity.setdefault("updated_at", ts)
        entity.setdefault("version", 1)
    else:
        # Ledger entities (TransferLink, FSAContribution) only carry id+created_at.
        ts = iso_format(now())
        entity.setdefault("created_at", ts)
    return entity


def bump(entity: dict[str, Any]) -> None:
    """Refresh updated_at and increment version on a primary entity."""
    if "version" in entity:
        entity["version"] = int(entity["version"]) + 1
    if "updated_at" in entity:
        entity["updated_at"] = iso_format(now())


def check_occ(entity: dict[str, Any], supplied: Any) -> None:
    """Compare a supplied OCC version against the entity's current version."""
    if supplied is None:
        return
    try:
        supplied_int = int(supplied)
    except (TypeError, ValueError):
        raise ApiError("ERR_VERSION_CONFLICT", "version must be an integer")
    if int(entity.get("version", -1)) != supplied_int:
        raise ApiError("ERR_VERSION_CONFLICT", "version does not match current resource")


def get_json_body() -> dict[str, Any]:
    """Tolerant JSON body parser — empty body yields {}."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def require_fields(body: dict[str, Any], *names: str) -> None:
    missing = [n for n in names if body.get(n) is None]
    if missing:
        raise ApiError("ERR_VALIDATION", f"Missing required fields: {', '.join(missing)}")


def parse_pagination() -> tuple[int, int]:
    """Parse limit/offset from query string; raises ERR_INVALID_PAGINATION on bounds violation."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_PAGINATION", "limit and offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION", "limit must be in [1,100]; offset must be >= 0")
    return limit, offset


def paginate_list(items: list, limit: int, offset: int) -> tuple[list, dict[str, Any]]:
    """Slice a sorted list and produce the pagination meta block."""
    total = len(items)
    sliced = items[offset : offset + limit]
    has_more = (offset + limit) < total
    return sliced, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }


def positive_int(value: Any, field: str, *, allow_zero: bool = False) -> int:
    """Strictly check int-ness — booleans, floats, and non-numeric strings are rejected."""
    if isinstance(value, bool):
        raise ApiError("ERR_VALIDATION", f"{field} must be an integer")
    if not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", f"{field} must be an integer")
    if allow_zero:
        if value < 0:
            raise ApiError("ERR_VALIDATION", f"{field} must be >= 0")
    else:
        if value <= 0:
            raise ApiError("ERR_INVALID_AMOUNT", f"{field} must be > 0")
    return value
