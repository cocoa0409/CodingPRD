"""Shared helpers: common-field stamping, OCC, pagination, body parsing."""
from __future__ import annotations

from typing import Any

from flask import request

from .clock import iso_format, real_now
from .errors import ApiError
from .store import gen_id


def stamp_new(entity: dict[str, Any], *, with_common: bool = True) -> dict[str, Any]:
    """Assign id and (optionally) created_at/updated_at/version on a new entity."""
    entity.setdefault("id", gen_id())
    ts = iso_format(real_now())
    if with_common:
        entity.setdefault("created_at", ts)
        entity.setdefault("updated_at", ts)
        entity.setdefault("version", 1)
    else:
        # Append-only entities (WaitlistEntry, UtilityReading, TowEvent) only carry id+created_at.
        entity.setdefault("created_at", ts)
    return entity


def bump(entity: dict[str, Any]) -> None:
    """Refresh updated_at and increment version — only for primary (versioned) entities."""
    if "version" in entity:
        entity["version"] = int(entity["version"]) + 1
    if "updated_at" in entity:
        entity["updated_at"] = iso_format(real_now())


def check_if_match(entity: dict[str, Any]) -> None:
    """Verify the request's If-Match header equals the entity's current version (PRD §2.6).

    Raises ERR_VERSION_CONFLICT when missing or mismatched. Only used for PATCH/PUT.
    """
    raw = request.headers.get("If-Match")
    if raw is None:
        raise ApiError("ERR_VERSION_CONFLICT", "If-Match header required")
    try:
        supplied = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VERSION_CONFLICT", "If-Match header must be an integer")
    if int(entity.get("version", -1)) != supplied:
        raise ApiError("ERR_VERSION_CONFLICT", "If-Match header does not match current version")


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
        raise ApiError("ERR_BAD_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body: dict[str, Any], *names: str) -> None:
    missing = [n for n in names if body.get(n) is None]
    if missing:
        raise ApiError("ERR_BAD_REQUEST", f"Missing required fields: {', '.join(missing)}")


def parse_pagination() -> tuple[int, int]:
    """Parse `limit`/`offset` (PRD §2.3). Default 10/0; bounds [1,100] / [0,]."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_BAD_REQUEST", "limit and offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_BAD_REQUEST", "limit must be in [1,100]; offset must be >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, dict[str, Any]]:
    total = len(items)
    sliced = items[offset : offset + limit]
    return sliced, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


def positive_int(value: Any, field: str, *, allow_zero: bool = False):
    if isinstance(value, bool):
        raise ApiError("ERR_BAD_REQUEST", f"{field} must be an integer")
    if not isinstance(value, int):
        raise ApiError("ERR_BAD_REQUEST", f"{field} must be an integer")
    if allow_zero:
        if value < 0:
            raise ApiError("ERR_BAD_REQUEST", f"{field} must be >= 0")
    else:
        if value <= 0:
            raise ApiError("ERR_BAD_REQUEST", f"{field} must be > 0")
    return value


def positive_number(value: Any, field: str):
    if isinstance(value, bool):
        raise ApiError("ERR_BAD_REQUEST", f"{field} must be a number")
    if not isinstance(value, (int, float)):
        raise ApiError("ERR_BAD_REQUEST", f"{field} must be a number")
    if value <= 0:
        raise ApiError("ERR_BAD_REQUEST", f"{field} must be > 0")
    return value
