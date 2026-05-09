"""Shared helpers: monetary rounding, ISO 8601 parsing, pagination param coercion."""
from __future__ import annotations

import calendar
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from flask import request

from errors import APIError, ERR_VALIDATION


# -----------------------------------------------------------------------------
# Money / numeric rounding
# -----------------------------------------------------------------------------
TWOPLACES = Decimal("0.01")


def to_decimal(value: Any) -> Decimal:
    """Convert int/float/str to Decimal robustly; floats route through str() to
    avoid binary noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int,)):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise APIError(ERR_VALIDATION, f"Expected numeric value, got {type(value).__name__}.", 422)


def round2(value: Any) -> float:
    """Round to two decimal places using ROUND_HALF_UP and return as float."""
    d = to_decimal(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    return float(d)


def round2_dec(value: Any) -> Decimal:
    return to_decimal(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


# -----------------------------------------------------------------------------
# ISO 8601 datetime parsing
# -----------------------------------------------------------------------------
def parse_iso(s: Any, *, field: str = "timestamp") -> datetime:
    if not isinstance(s, str) or not s:
        raise APIError(ERR_VALIDATION, f"Invalid {field}: not a string.", 422)
    raw = s
    # Accept trailing Z (Zulu) by translating to +00:00 for fromisoformat.
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise APIError(ERR_VALIDATION, f"Invalid ISO 8601 {field}: '{s}'.", 422)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def iso_format(t: datetime) -> str:
    """ISO 8601 UTC, three fractional digits, trailing Z."""
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    else:
        t = t.astimezone(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


# -----------------------------------------------------------------------------
# Pagination
# -----------------------------------------------------------------------------
def parse_pagination(default_limit: int = 10, max_limit: int = 100) -> tuple[int, int]:
    """Returns (limit, offset). Clamps per PRD §2.3."""
    raw_limit = request.args.get("limit", default_limit)
    raw_offset = request.args.get("offset", 0)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise APIError(ERR_VALIDATION, "limit must be an integer.", 422)
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise APIError(ERR_VALIDATION, "offset must be an integer.", 422)
    if limit < 1:
        limit = 1
    if limit > max_limit:
        limit = max_limit
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset:offset + limit], total


# -----------------------------------------------------------------------------
# Body / required-field helpers
# -----------------------------------------------------------------------------
def get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError(ERR_VALIDATION, "Request body must be a JSON object.", 422)
    return body


def require_field(body: dict, name: str):
    if name not in body or body[name] is None or (isinstance(body[name], str) and not body[name].strip()):
        raise APIError(ERR_VALIDATION, f"Missing required field: {name}.", 422)
    return body[name]


# -----------------------------------------------------------------------------
# Calendar helpers
# -----------------------------------------------------------------------------
def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def last_day_of_month(year: int, month: int) -> datetime:
    """Return the last instant (start of last day) of the given month, UTC."""
    last_day = days_in_month(year, month)
    return datetime(year, month, last_day, 0, 0, 0, tzinfo=timezone.utc)
