"""Shared request-validation, datetime, pagination, and rounding helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import raise_err, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3: limit default 10, min 1, capped at 100; offset >= 0)
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
        if limit < MIN_LIMIT:
            raise_err(ERR_INVALID_REQUEST, f"limit must be >= {MIN_LIMIT}")
        if limit > MAX_LIMIT:
            limit = MAX_LIMIT  # capped at the maximum per PRD 2.3

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


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
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


def require_int(body: dict, name: str) -> int:
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return value


def optional_int(body: dict, name: str):
    if name not in body or body[name] is None:
        return None
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return value


def require_number(body: dict, name: str):
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    return value


def optional_number(body: dict, name: str):
    if name not in body or body[name] is None:
        return None
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    return value


def optional_bool(body: dict, name: str, default=False):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return value


def require_enum(body: dict, name: str, allowed: set) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return value


def optional_str_array(body: dict, name: str, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, list) or any(not isinstance(v, str) or v == "" for v in value):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an array of non-empty strings")
    return list(value)


# ---------------------------------------------------------------------------
# Date / datetime parsing and formatting
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def require_date(body: dict, name: str) -> str:
    value = require_string(body, name)
    if not _DATE_RE.match(value):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an ISO date YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a valid calendar date")
    return value


def parse_iso8601(value, field_name: str) -> datetime:
    """Parse an ISO 8601 timestamp to an aware UTC datetime for comparison."""
    if not isinstance(value, str) or value.strip() == "":
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
    return value


def fmt_dt(dt: datetime) -> str:
    """Normalize an aware datetime to ISO 8601 UTC with a trailing Z; whole
    seconds render without a fractional part (echoing the canonical clock
    format), sub-second instants render with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Rounding helpers (PRD 2.6: half-up to a whole cent at the line level)
# ---------------------------------------------------------------------------

def round_half_up_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value) -> Decimal:
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# List helpers
# ---------------------------------------------------------------------------

def apply_filters(items: list, filter_names: list) -> list:
    out = items
    for name in filter_names:
        value = request.args.get(name)
        if value is not None and value != "":
            out = [it for it in out if str(it.get(name)) == value]
    return out


def sort_by_created_at(items: list) -> list:
    # created_at strings sort lexicographically; _seq breaks same-ms ties in
    # creation order.
    return sorted(items, key=lambda it: (it.get("created_at", ""), it.get("_seq", 0)))
