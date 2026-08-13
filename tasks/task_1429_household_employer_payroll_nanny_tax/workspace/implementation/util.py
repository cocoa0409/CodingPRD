"""Shared request-validation, pagination, date, and rounding helpers."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
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
            raise_err(ERR_INVALID_REQUEST, f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")

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


def optional_string(body: dict, name: str):
    value = optional_field(body, name, None)
    if value is not None and (not isinstance(value, str) or value == ""):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string when present")
    return value


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def require_int(body: dict, name: str, minimum: int | None = None) -> int:
    value = require_field(body, name)
    if not is_int(value):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return value


def optional_int(body: dict, name: str, default: int, minimum: int | None = None) -> int:
    if name not in body or body[name] is None:
        return default
    return require_int(body, name, minimum)


def require_bool(body: dict, name: str) -> bool:
    value = require_field(body, name)
    if not isinstance(value, bool):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return value


def require_number(body: dict, name: str):
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
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
_FEIN_RE = re.compile(r"^\d{9}$")


def parse_date(value, field_name: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise_err(ERR_INVALID_REQUEST, f"Field {field_name} must be an ISO date YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"Field {field_name} must be a valid calendar date")
    return value


def require_date(body: dict, name: str) -> str:
    return parse_date(require_field(body, name), name)


def require_fein(body: dict, name: str) -> str:
    value = require_string(body, name)
    if not _FEIN_RE.match(value):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be exactly 9 digits")
    return value


def parse_iso8601(value, field_name: str):
    """Validate an ISO 8601 timestamp string; return the canonical text."""
    if not isinstance(value, str) or value.strip() == "":
        raise_err(ERR_INVALID_REQUEST, f"Field {field_name} must be an ISO 8601 timestamp")
    try:
        db.parse_iso_dt(value)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"Field {field_name} must be a valid ISO 8601 timestamp")
    return value


# ---------------------------------------------------------------------------
# Rounding helpers (round half-up; never Python's banker's round)
# ---------------------------------------------------------------------------

def round_half_up_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def to_decimal_rate(value) -> Decimal:
    """Convert a JSON numeric rate to Decimal exactly via its string form."""
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# List helpers
# ---------------------------------------------------------------------------

def apply_filters(items: list, filter_names: list[str]) -> list:
    out = items
    for name in filter_names:
        value = request.args.get(name)
        if value is not None and value != "":
            out = [it for it in out if str(it.get(name)) == value]
    return out


def sort_by_created_at(items: list) -> list:
    return sorted(items, key=lambda it: (it.get("created_at", ""), it.get("_seq", 0)))
