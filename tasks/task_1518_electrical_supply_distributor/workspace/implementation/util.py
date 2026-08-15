"""Shared request-validation, pagination, numeric, and date helpers."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from db import clock_date, touch
from errors import raise_err, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3: limit default 10, min 1, max 100; offset default 0)
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


def paginate(items: list) -> tuple[list, int, int, int]:
    """Return (page_items, limit, offset, total_count). Items pre-sorted."""
    limit, offset = parse_pagination()
    total = len(items)
    return items[offset : offset + limit], limit, offset, total


# ---------------------------------------------------------------------------
# Numbers — Decimal everywhere; never float math for money (PRD §2.7)
# ---------------------------------------------------------------------------


def to_decimal(value):
    """Convert a JSON number (int/float, never bool/str) to Decimal."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def num(value):
    """Serialize a Decimal (or int) as a JSON number."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# Body field validation (PRD §2.9 — shape errors are ERR_INVALID_REQUEST)
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
    if not isinstance(value, str) or value.strip() == "":
        raise_err(ERR_INVALID_REQUEST, f"Field must be a non-empty string: {name}")
    return value


def require_int(body: dict, name: str) -> int:
    value = require_field(body, name)
    if not is_int(value):
        raise_err(ERR_INVALID_REQUEST, f"Field must be an integer: {name}")
    return value


def require_number(body: dict, name: str) -> Decimal:
    value = require_field(body, name)
    dec = to_decimal(value)
    if dec is None:
        raise_err(ERR_INVALID_REQUEST, f"Field must be a number: {name}")
    return dec


def optional_number(body: dict, name: str):
    """Decimal or None; explicit null counts as absent."""
    if name not in body or body[name] is None:
        return None
    dec = to_decimal(body[name])
    if dec is None:
        raise_err(ERR_INVALID_REQUEST, f"Field must be a number: {name}")
    return dec


def optional_bool(body: dict, name: str, default: bool = False) -> bool:
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], bool):
        raise_err(ERR_INVALID_REQUEST, f"Field must be a boolean: {name}")
    return body[name]


# ---------------------------------------------------------------------------
# Dates and instants
# ---------------------------------------------------------------------------


def parse_date(value):
    """Parse an ISO 8601 date string -> date, or None."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def require_date(body: dict, name: str) -> str:
    """Require an ISO date field; returns the normalized 'YYYY-MM-DD' string."""
    raw = require_field(body, name)
    parsed = parse_date(raw)
    if parsed is None:
        raise_err(ERR_INVALID_REQUEST, f"Field must be an ISO 8601 date: {name}")
    return parsed.isoformat()


def parse_instant(value):
    """Parse an ISO 8601 instant -> aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        parsed_date = parse_date(value)
        if parsed_date is None:
            return None
        return datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_instant(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def is_valid_month(value) -> bool:
    return isinstance(value, str) and _MONTH_RE.match(value) is not None


# ---------------------------------------------------------------------------
# Quote lazy expiry (PRD §3.4): any read or transition attempt against a
# DRAFT or SUBMITTED quote whose valid_until has passed moves it to EXPIRED.
# Submit/award handle expiry explicitly (ERR_QUOTE_EXPIRED) instead.
# ---------------------------------------------------------------------------


def maybe_expire_quote(quote: dict) -> None:
    if quote["status"] in ("DRAFT", "SUBMITTED"):
        valid_until = parse_date(quote["valid_until"])
        if valid_until is not None and clock_date() > valid_until:
            quote["status"] = "EXPIRED"
            touch(quote)
