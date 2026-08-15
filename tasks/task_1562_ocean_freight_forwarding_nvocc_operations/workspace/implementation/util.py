"""Shared request-validation, pagination, and rounding helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import raise_err, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# Pagination (scaffold section 1.0: limit/offset, defaults 10/0, min 1, max 100)
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
    total = len(items)
    return items[offset: offset + limit], total


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
    v = body[name]
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a string")
    return v


def require_int(body: dict, name: str, minimum: int | None = None, maximum: int | None = None) -> int:
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be <= {maximum}")
    return value


def optional_int(body: dict, name: str, minimum: int | None = None):
    if name not in body or body[name] is None:
        return None
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return value


def require_number(body: dict, name: str, strictly_positive: bool = False):
    """Numeric field that may be int or float (weights, volumes, quantities)."""
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    if strictly_positive and not (value > 0):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be > 0")
    return value


def require_enum(body: dict, name: str, allowed: set[str]) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return value


def optional_enum(body: dict, name: str, allowed: set[str]):
    if name not in body or body[name] is None:
        return None
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return value


def require_list(body: dict, name: str) -> list:
    value = require_field(body, name)
    if not isinstance(value, list):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an array")
    return value


def parse_iso8601(value, field_name: str) -> datetime:
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


def require_ts(body: dict, name: str) -> datetime:
    value = require_field(body, name)
    return parse_iso8601(value, name)


# ---------------------------------------------------------------------------
# Rounding (PRD section 2.7: round half up; Decimal for money)
# ---------------------------------------------------------------------------

def dec(value) -> Decimal:
    """Exact Decimal view of a JSON number (int or float)."""
    return Decimal(str(value))


def round_half_up_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_3dp(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# List filters / sorting
# ---------------------------------------------------------------------------

def apply_filters(items: list, filter_names: list[str]) -> list:
    out = items
    for name in filter_names:
        value = request.args.get(name)
        if value is not None and value != "":
            out = [it for it in out if str(it.get(name)) == value]
    return out


def sort_by_created_at(items: list) -> list:
    """created_at ascending (PRD section 2.3); insertion order breaks ties."""
    return sorted(items, key=lambda it: (it.get("created_at", ""), it.get("_seq", 0)))


def pub(entity: dict) -> dict:
    """Public serialization: strip internal underscore-prefixed fields."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
