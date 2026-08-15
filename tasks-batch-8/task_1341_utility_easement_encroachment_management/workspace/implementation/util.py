"""Shared request-validation, pagination, and datetime helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from constants import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT
from errors import raise_err


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3: limit default 10, min 1, max 100; offset default 0)
# ---------------------------------------------------------------------------

def parse_pagination() -> tuple[int, int]:
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise_err("ERR_INVALID_REQUEST", f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")

    if raw_offset is None or raw_offset == "":
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise_err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset : offset + limit], total


def sort_by_created_at(items: list) -> list:
    """created_at ASC; ties broken by creation sequence (never id)."""
    return sorted(items, key=lambda it: (it.get("created_at", ""), it.get("_seq", 0)))


def apply_filters(items: list, filter_names: list[str]) -> list:
    out = items
    for name in filter_names:
        value = request.args.get(name)
        if value is not None and value != "":
            out = [it for it in out if str(it.get(name)) == value]
    return out


# ---------------------------------------------------------------------------
# Body field validation
# ---------------------------------------------------------------------------

def get_json_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise_err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    return body[name]


def optional_field(body: dict, name: str, default=None):
    if name not in body or body[name] is None:
        return default
    return body[name]


def require_string(body: dict, name: str) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value == "":
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a non-empty string")
    return value


def require_number(body: dict, name: str) -> Decimal:
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a number")
    return Decimal(str(value))


def optional_number(body: dict, name: str, default: Decimal | None = None) -> Decimal | None:
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a number")
    return Decimal(str(value))


def require_int(body: dict, name: str) -> int:
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    return value


def optional_int(body: dict, name: str, default: int | None = None) -> int | None:
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    return value


def require_bool(body: dict, name: str) -> bool:
    value = require_field(body, name)
    if not isinstance(value, bool):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return value


def optional_bool(body: dict, name: str, default: bool = False) -> bool:
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return value


def require_list(body: dict, name: str) -> list:
    value = require_field(body, name)
    if not isinstance(value, list):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an array")
    return value


def require_enum(body: dict, name: str, allowed: set[str]) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value not in allowed:
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(allowed)}")
    return value


# ---------------------------------------------------------------------------
# Date / datetime parsing
# ---------------------------------------------------------------------------

def parse_iso8601(value, field_name: str) -> datetime:
    """Parse an ISO 8601 timestamp to an aware UTC datetime."""
    if not isinstance(value, str) or value.strip() == "":
        raise_err("ERR_INVALID_REQUEST", f"Field {field_name} must be an ISO 8601 timestamp")
    text = value.strip()
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(text)
    except ValueError:
        raise_err("ERR_INVALID_REQUEST", f"Field {field_name} must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_ts(body: dict, name: str) -> datetime:
    value = require_field(body, name)
    return parse_iso8601(value, name)


def parse_ts_stored(value: str | None) -> datetime | None:
    """Parse a stored canonical timestamp; returns None for missing."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Rounding helpers (PRD 2.6: half-up everywhere)
# ---------------------------------------------------------------------------

def round_half_up_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_dp(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal("1").scaleb(-places), rounding=ROUND_HALF_UP)
