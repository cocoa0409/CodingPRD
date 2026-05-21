"""Shared helpers: common-fields stamping, OCC, pagination, payload helpers."""
from __future__ import annotations

from typing import Any

from flask import request

from .clock import iso_format, now
from .errors import ApiError
from .store import gen_id


def stamp_new(entity: dict[str, Any], *, with_common: bool = True) -> dict[str, Any]:
    """Assign id and (optionally) created_at/updated_at/version (§2.4)."""
    entity.setdefault("id", gen_id())
    ts = iso_format(now())
    entity.setdefault("created_at", ts)
    if with_common:
        entity.setdefault("updated_at", ts)
        entity.setdefault("version", 1)
    return entity


def bump(entity: dict[str, Any]) -> None:
    """Refresh updated_at and increment version on a primary entity."""
    if "version" in entity:
        entity["version"] = int(entity["version"]) + 1
    if "updated_at" in entity:
        entity["updated_at"] = iso_format(now())


def check_occ(entity: dict[str, Any], supplied: Any) -> None:
    """Compare a supplied OCC version against the entity's current version (§2.6)."""
    if supplied is None:
        return
    if isinstance(supplied, bool):
        raise ApiError("ERR_VERSION_CONFLICT", "version must be an integer")
    try:
        supplied_int = int(supplied)
    except (TypeError, ValueError):
        raise ApiError("ERR_VERSION_CONFLICT", "version must be an integer")
    if int(entity.get("version", -1)) != supplied_int:
        raise ApiError("ERR_VERSION_CONFLICT", "version does not match current resource")


def get_json_body() -> dict[str, Any]:
    """Tolerant body parser — empty body yields {}."""
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
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "limit and offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_VALIDATION", "limit must be in [1,100]; offset must be >= 0")
    return limit, offset


def paginate_list(items: list, limit: int, offset: int) -> tuple[list, dict[str, Any]]:
    total = len(items)
    sliced = items[offset : offset + limit]
    has_more = (offset + limit) < total
    return sliced, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }


def as_int(value: Any, field: str, *, allow_zero: bool = True, min_value: int | None = None, max_value: int | None = None) -> int:
    """Strict integer coercion; rejects bools, floats, and non-numeric strings."""
    if isinstance(value, bool):
        raise ApiError("ERR_VALIDATION", f"{field} must be an integer")
    if not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", f"{field} must be an integer")
    if not allow_zero and value <= 0:
        raise ApiError("ERR_VALIDATION", f"{field} must be > 0")
    if min_value is not None and value < min_value:
        raise ApiError("ERR_VALIDATION", f"{field} must be >= {min_value}")
    if max_value is not None and value > max_value:
        raise ApiError("ERR_VALIDATION", f"{field} must be <= {max_value}")
    return value


def as_number(value: Any, field: str, *, gt: float | None = None, le: float | None = None) -> float:
    """Numeric coercion that accepts ints and floats; rejects bools and other types."""
    if isinstance(value, bool):
        raise ApiError("ERR_VALIDATION", f"{field} must be a number")
    if not isinstance(value, (int, float)):
        raise ApiError("ERR_VALIDATION", f"{field} must be a number")
    v = float(value)
    if gt is not None and not (v > gt):
        raise ApiError("ERR_VALIDATION", f"{field} must be > {gt}")
    if le is not None and not (v <= le):
        raise ApiError("ERR_VALIDATION", f"{field} must be <= {le}")
    return v


def as_string(value: Any, field: str, *, min_len: int = 1, max_len: int | None = None, trim: bool = False) -> str:
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", f"{field} must be a string")
    v = value.strip() if trim else value
    if len(v) < min_len:
        raise ApiError("ERR_VALIDATION", f"{field} must be non-empty (>= {min_len} chars after trim)")
    if max_len is not None and len(v) > max_len:
        raise ApiError("ERR_VALIDATION", f"{field} must be <= {max_len} characters")
    return v


def as_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ApiError("ERR_VALIDATION", f"{field} must be a boolean")
    return value
