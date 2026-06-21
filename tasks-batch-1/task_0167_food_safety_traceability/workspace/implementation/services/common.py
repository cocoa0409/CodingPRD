"""Shared helpers: body validation, datetime parsing, decimal rounding,
pagination, and request-body access.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from flask import request

from errors import err

# Pagination defaults (PRD §2.3 / scaffold §1.0).
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def get_json_body() -> dict:
    """Return the parsed JSON body as a dict; tolerate empty bodies."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_fields(body: dict, names) -> None:
    """ERR_INVALID_REQUEST when any required field is absent or null."""
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {n}")


def require_str(body: dict, name: str) -> str:
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a non-empty string")
    return v


def require_number(body: dict, name: str, positive: bool = False) -> float:
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a number")
    if positive and not (v > 0):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be greater than zero")
    return v


def require_int(body: dict, name: str) -> int:
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    return v


def require_bool(body: dict, name: str) -> bool:
    v = body.get(name)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return v


def optional_bool(body: dict, name: str, default: bool) -> bool:
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return v


# ---- datetime parsing -------------------------------------------------------

def parse_dt(value: Any, field: str) -> datetime:
    """Parse an ISO 8601 timestamp into a timezone-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive timestamps are treated
    as UTC.
    """
    if not isinstance(value, str) or not value:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 timestamp")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"Field {field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt: datetime) -> str:
    """Render a UTC datetime as ISO 8601 with three fractional digits + 'Z'."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_days(dt: datetime, days: int) -> datetime:
    """Add a whole number of days to a datetime (PRD §2.9)."""
    return dt + timedelta(days=days)


# ---- decimal / quantity rounding -------------------------------------------

def round_qty(value) -> float:
    """Round half up to three decimal places (PRD §2.9)."""
    q = Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return float(q)


# ---- pagination -------------------------------------------------------------

def parse_pagination() -> tuple[int, int]:
    """Read limit/offset query params with defaults and bounds (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = LIMIT_DEFAULT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < LIMIT_MIN:
            limit = LIMIT_MIN
        elif limit > LIMIT_MAX:
            limit = LIMIT_MAX

    if raw_offset is None:
        offset = OFFSET_DEFAULT
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0

    return limit, offset


def created_sort_key(rec: dict):
    """Stable ascending order by created_at then insertion sequence."""
    return (rec.get("created_at", ""), rec.get("_seq", 0))


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
