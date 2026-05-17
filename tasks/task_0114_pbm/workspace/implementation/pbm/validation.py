"""Shared validators (pagination, OCC, body parsing, decimal helpers)."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from flask import request

from .errors import (
    APIError,
    ERR_VALIDATION,
    ERR_VERSION_CONFLICT,
    ERR_RESOURCE_NOT_FOUND,
    ERR_INVALID_STATE,
)


# ----- request body helpers -----

def get_json_body() -> dict:
    """Return the request body as a dict; treat missing/empty as {}."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError(ERR_VALIDATION, "Request body must be a JSON object", 422)
    return body


# ----- pagination -----

def parse_pagination() -> tuple[int, int]:
    """Read ?limit and ?offset; enforce 1..100 / >=0 per PRD §2.3 / scaffold defaults."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise APIError(ERR_VERSION_CONFLICT, "limit/offset must be integers", 409)
    if limit < 1 or limit > 100:
        raise APIError(ERR_VERSION_CONFLICT, "limit must be between 1 and 100", 409)
    if offset < 0:
        raise APIError(ERR_VERSION_CONFLICT, "offset must be >= 0", 409)
    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    return items[offset: offset + limit], len(items)


# ----- OCC -----

def check_version(body: dict, entity: dict) -> None:
    """When `version` is supplied in body, compare to entity['version']."""
    if "version" not in body or body["version"] is None:
        return
    try:
        supplied = int(body["version"])
    except (TypeError, ValueError):
        raise APIError(ERR_VERSION_CONFLICT, "version must be an integer", 409)
    if supplied != int(entity["version"]):
        raise APIError(
            ERR_VERSION_CONFLICT,
            f"version mismatch: supplied={supplied}, current={entity['version']}",
            409,
        )


# ----- generic field validators -----

def require_field(body: dict, key: str, *, allow_zero: bool = True) -> Any:
    if key not in body or body[key] is None:
        raise APIError(ERR_VALIDATION, f"missing required field '{key}'", 422)
    val = body[key]
    if isinstance(val, str) and not val.strip():
        raise APIError(ERR_VALIDATION, f"field '{key}' must be non-empty", 422)
    if not allow_zero and isinstance(val, (int, float)) and val == 0:
        raise APIError(ERR_VALIDATION, f"field '{key}' must be non-zero", 422)
    return val


def as_int(value: Any, key: str) -> int:
    try:
        if isinstance(value, bool):
            raise TypeError
        return int(value)
    except (TypeError, ValueError):
        raise APIError(ERR_VALIDATION, f"field '{key}' must be an integer", 422)


def as_nonneg_int(value: Any, key: str) -> int:
    v = as_int(value, key)
    if v < 0:
        raise APIError(ERR_VALIDATION, f"field '{key}' must be >= 0", 422)
    return v


def as_pos_int(value: Any, key: str) -> int:
    v = as_int(value, key)
    if v < 1:
        raise APIError(ERR_VALIDATION, f"field '{key}' must be >= 1", 422)
    return v


def as_number(value: Any, key: str) -> float:
    try:
        if isinstance(value, bool):
            raise TypeError
        return float(value)
    except (TypeError, ValueError):
        raise APIError(ERR_VALIDATION, f"field '{key}' must be a number", 422)


def as_bool(value: Any, key: str, *, default: bool | None = None) -> bool:
    if value is None:
        if default is not None:
            return default
        raise APIError(ERR_VALIDATION, f"field '{key}' must be a boolean", 422)
    if isinstance(value, bool):
        return value
    raise APIError(ERR_VALIDATION, f"field '{key}' must be a boolean", 422)


# ----- decimal rounding (cents) -----

def round_half_up_cents(value) -> int:
    """Round a numeric value to integer cents using HALF-UP semantics.

    Always operate via Decimal to avoid IEEE 754 drift.
    """
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
