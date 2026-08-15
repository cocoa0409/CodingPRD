"""Shared request-validation, datetime, rounding, and pagination helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import raise_err, ERR_VALIDATION, ERR_NOT_FOUND


# ---------------------------------------------------------------------------
# Pagination
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
            raise_err(ERR_VALIDATION, "limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise_err(
                ERR_VALIDATION,
                f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}",
            )

    if raw_offset is None or raw_offset == "":
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_VALIDATION, "offset must be >= 0")

    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset : offset + limit], total


def sort_created(items: list) -> list:
    """Sort by creation timestamp ascending; _seq breaks same-millisecond ties."""
    return sorted(items, key=lambda it: (it.get("created_at", ""), it.get("_seq", 0)))


def query_arg(name: str):
    """Query-string filter value; None when absent or empty."""
    value = request.args.get(name)
    return value if value not in (None, "") else None


# ---------------------------------------------------------------------------
# Body field validation
# ---------------------------------------------------------------------------

def get_json_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_VALIDATION, "Request body must be a JSON object")
    return body


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise_err(ERR_VALIDATION, f"Missing required field: {name}")
    return body[name]


def optional_field(body: dict, name: str, default=None):
    if name not in body or body[name] is None:
        return default
    return body[name]


def require_string(body: dict, name: str) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value == "":
        raise_err(ERR_VALIDATION, f"Field {name} must be a non-empty string")
    return value


def optional_string(body: dict, name: str, default=None):
    value = optional_field(body, name, default)
    if value is not None and not isinstance(value, str):
        raise_err(ERR_VALIDATION, f"Field {name} must be a string")
    return value


def require_int(body: dict, name: str, minimum: int | None = None,
                maximum: int | None = None) -> int:
    value = require_field(body, name)
    if not is_int(value):
        raise_err(ERR_VALIDATION, f"Field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise_err(ERR_VALIDATION, f"Field {name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise_err(ERR_VALIDATION, f"Field {name} must be <= {maximum}")
    return value


def optional_int(body: dict, name: str, default=None, minimum: int | None = None):
    value = optional_field(body, name, default)
    if value is None:
        return value
    if not is_int(value):
        raise_err(ERR_VALIDATION, f"Field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise_err(ERR_VALIDATION, f"Field {name} must be >= {minimum}")
    return value


def require_bool(body: dict, name: str) -> bool:
    value = require_field(body, name)
    if not isinstance(value, bool):
        raise_err(ERR_VALIDATION, f"Field {name} must be a boolean")
    return value


def optional_bool(body: dict, name: str, default=False) -> bool:
    value = optional_field(body, name, default)
    if not isinstance(value, bool):
        raise_err(ERR_VALIDATION, f"Field {name} must be a boolean")
    return value


def require_enum(body: dict, name: str, allowed: set[str]) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value not in allowed:
        raise_err(ERR_VALIDATION, f"Field {name} must be one of {sorted(allowed)}")
    return value


def require_id_array(body: dict, name: str, default=None) -> list:
    value = optional_field(body, name, default if default is not None else [])
    if not isinstance(value, list):
        raise_err(ERR_VALIDATION, f"Field {name} must be an array")
    for el in value:
        if not isinstance(el, str):
            raise_err(ERR_VALIDATION, f"Field {name} must contain string ids")
    return value


# ---------------------------------------------------------------------------
# ISO 8601 datetimes
# ---------------------------------------------------------------------------

def parse_iso8601(value, field_name: str = "timestamp") -> datetime:
    """Parse an ISO 8601 timestamp to an aware UTC datetime for comparison."""
    if not isinstance(value, str) or value == "":
        raise_err(ERR_VALIDATION, f"Field {field_name} must be an ISO 8601 timestamp")
    text = value.strip()
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(text)
    except ValueError:
        raise_err(ERR_VALIDATION, f"Field {field_name} must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_ts(body: dict, name: str) -> str:
    value = require_field(body, name)
    parse_iso8601(value, name)  # validates
    return value


def render_dt(dt: datetime) -> str:
    """Render a computed datetime as ISO 8601 UTC; fractional digits only when
    non-zero, so e.g. 2026-08-01T00:00:00Z + 180d renders 2027-01-28T00:00:00Z."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------

def round_half_up_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Reference resolution
# ---------------------------------------------------------------------------

def get_or_404(store: dict, entity_id, label: str) -> dict:
    if not isinstance(entity_id, str) or entity_id not in store:
        raise_err(ERR_NOT_FOUND, f"{label} not found: {entity_id}")
    return store[entity_id]
