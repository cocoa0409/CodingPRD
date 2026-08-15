"""Shared request-validation and pagination helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

from errors import raise_err, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3: limit default 10, min 1, max 100; offset default 0)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination() -> tuple[int, int]:
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise_err(
                ERR_INVALID_REQUEST,
                f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}",
            )

    if raw_offset is None or raw_offset == "":
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    """Return (page_items, total_count). Items must already be sorted."""
    total = len(items)
    return items[offset : offset + limit], total


# ---------------------------------------------------------------------------
# Body field validation
# ---------------------------------------------------------------------------

def get_json_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def has_field(body: dict, name: str) -> bool:
    return name in body and body[name] is not None


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return body[name]


def optional_field(body: dict, name: str, default=None):
    if name not in body or body[name] is None:
        return default
    return body[name]


def require_string(body: dict, name: str) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value == "":
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return value


def optional_string(body: dict, name: str):
    if name not in body or body[name] is None:
        return None
    value = body[name]
    if not isinstance(value, str) or value == "":
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return value


def _is_number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def require_number(body: dict, name: str, minimum: float | None = None,
                   exclusive_min: bool = False):
    value = require_field(body, name)
    if not _is_number(value):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    if minimum is not None:
        if exclusive_min and not (value > minimum):
            raise_err(ERR_INVALID_REQUEST, f"Field {name} must be > {minimum}")
        if not exclusive_min and not (value >= minimum):
            raise_err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return value


def optional_number(body: dict, name: str, default=None, minimum: float | None = None,
                    exclusive_min: bool = False):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not _is_number(value):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    if minimum is not None:
        if exclusive_min and not (value > minimum):
            raise_err(ERR_INVALID_REQUEST, f"Field {name} must be > {minimum}")
        if not exclusive_min and not (value >= minimum):
            raise_err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return value


def require_int(body: dict, name: str, minimum: int | None = None,
                exclusive_min: bool = False) -> int:
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None:
        if exclusive_min and not (value > minimum):
            raise_err(ERR_INVALID_REQUEST, f"Field {name} must be > {minimum}")
        if not exclusive_min and not (value >= minimum):
            raise_err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return value


def optional_int(body: dict, name: str, default=None, minimum: int | None = None) -> int:
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return value


def require_bool(body, name: str) -> bool:
    value = require_field(body, name)
    if not isinstance(value, bool):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return value


def require_enum(body: dict, name: str, allowed: set[str]) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return value


# ---------------------------------------------------------------------------
# Date / datetime parsing
# ---------------------------------------------------------------------------

def parse_iso8601(value, field_name: str) -> datetime:
    """Parse an ISO 8601 timestamp to an aware UTC datetime for comparison."""
    if not isinstance(value, str) or value == "":
        raise_err(ERR_INVALID_REQUEST, f"Field {field_name} must be an ISO 8601 timestamp")
    text = value.strip()
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(text)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"Field {field_name} must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_ts(body: dict, name: str) -> str:
    value = require_field(body, name)
    parse_iso8601(value, name)  # validates
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an ISO 8601 timestamp string")
    return value


def to_decimal(value) -> Decimal:
    """Exact Decimal from a JSON number (via str to avoid float artifacts)."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise_err(ERR_INVALID_REQUEST, "Numeric value is not valid decimal")


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------

def round_half_up_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_half_up_4dp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def dec_to_float(value: Decimal) -> float:
    return float(value)


# ---------------------------------------------------------------------------
# List filters / ordering
# ---------------------------------------------------------------------------

def apply_filters(items: list, filter_names: list[str]) -> list:
    out = items
    for name in filter_names:
        value = request.args.get(name)
        if value is not None and value != "":
            out = [it for it in out if str(it.get(name)) == value]
    return out


def sort_by_created_at(items: list) -> list:
    # created_at strings sort lexicographically; id breaks ties for stability.
    return sorted(items, key=lambda it: (it.get("created_at", ""), it.get("id", "")))


def serialize(entity: dict) -> dict:
    """Public view: drop internal helper fields (prefixed with '_')."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_list(items: list) -> list:
    return [serialize(it) for it in items]
