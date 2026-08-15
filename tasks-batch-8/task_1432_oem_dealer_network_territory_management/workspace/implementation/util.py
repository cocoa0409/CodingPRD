"""Shared request-validation, pagination, and date helpers."""

from __future__ import annotations

import re
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import raise_err, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3: limit default 10, min 1, max 100; offset default 0)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def get_param(name: str):
    """Read a query parameter, falling back to a JSON body field (some
    harnesses pass GET payloads as a JSON body)."""
    value = request.args.get(name)
    if value is not None:
        return value
    body = request.get_json(silent=True)
    if isinstance(body, dict) and name in body:
        return body[name]
    return None


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


def require_int(body: dict, name: str, minimum: int | None = None) -> int:
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return value


def require_number(body: dict, name: str, minimum: float | None = None):
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    if minimum is not None and value < minimum:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return value


def require_enum(body: dict, name: str, allowed: set[str]) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return value


# ---------------------------------------------------------------------------
# Date / datetime parsing
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value, field_name: str) -> date:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise_err(ERR_INVALID_REQUEST, f"Field {field_name} must be an ISO date YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"Field {field_name} must be a valid calendar date")


def require_date(body: dict, name: str) -> str:
    value = require_string(body, name)
    parse_date(value, name)
    return value


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


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------

def round_half_up_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


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
    # _seq is a monotonic creation-order marker; it implements the spec's
    # "sorted by creation timestamp ascending" rule without millisecond ties.
    return sorted(items, key=lambda it: it.get("_seq", 0))
