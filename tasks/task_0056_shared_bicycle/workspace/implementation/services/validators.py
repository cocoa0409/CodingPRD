"""Generic input/pagination/OCC validators."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from flask import request

from constants import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from errors import ERR_VALIDATION, ERR_VERSION_CONFLICT, raise_err


def parse_pagination() -> Tuple[int, int]:
    """Return (limit, offset) from query params, enforcing PRD §2.3 bounds."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else PAGINATION_DEFAULT_LIMIT
    except (TypeError, ValueError):
        raise_err(ERR_VALIDATION, "limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else PAGINATION_DEFAULT_OFFSET
    except (TypeError, ValueError):
        raise_err(ERR_VALIDATION, "offset must be an integer")
    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise_err(
            ERR_VALIDATION,
            f"limit must be between {PAGINATION_MIN_LIMIT} and {PAGINATION_MAX_LIMIT}",
        )
    if offset < 0:
        raise_err(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def get_json_body() -> Dict[str, Any]:
    """Return parsed JSON body (empty dict if absent or malformed)."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise_err(ERR_VALIDATION, "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise_err(ERR_VALIDATION, "Request body must be a JSON object")
    return body


def require_fields(body: Dict[str, Any], *fields: str) -> None:
    for f in fields:
        if f not in body:
            raise_err(ERR_VALIDATION, f"Missing required field: {f}")


def check_version(body: Dict[str, Any], entity: Dict[str, Any]) -> None:
    """OCC check (PRD §2.4). Skipped when body has no 'version' key."""
    if "version" not in body:
        return
    body_version = body["version"]
    if not isinstance(body_version, int) or isinstance(body_version, bool):
        raise_err(ERR_VALIDATION, "version must be an integer")
    if body_version != entity.get("version"):
        raise_err(ERR_VERSION_CONFLICT, "Version mismatch (optimistic concurrency)")


def ensure_positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise_err(ERR_VALIDATION, f"{name} must be a positive integer")
    return value


def ensure_non_negative_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise_err(ERR_VALIDATION, f"{name} must be a non-negative integer")
    return value


def ensure_enum(value: Any, name: str, allowed) -> str:
    if value not in allowed:
        raise_err(ERR_VALIDATION, f"{name} must be one of {sorted(allowed)}")
    return value


def ensure_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_err(ERR_VALIDATION, f"{name} must be a number")
    return float(value)


def bump_version(entity: Dict[str, Any]) -> None:
    """Increment version and updated_at on every mutation."""
    if "version" in entity:
        entity["version"] = int(entity["version"]) + 1
    from time_utils import now_iso  # avoid circular at module load
    if "updated_at" in entity:
        entity["updated_at"] = now_iso()
