"""Shared request-validation and pagination helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone, date

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
        if isinstance(limit, bool) or limit < MIN_LIMIT or limit > MAX_LIMIT:
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
    return items[offset : offset + limit], total


def apply_filters(items: list, filters: dict) -> list:
    """Exact-match filtering on the given field values (None = not provided)."""
    out = items
    for field, value in filters.items():
        if value is not None:
            out = [it for it in out if it.get(field) == value]
    return out


# ---------------------------------------------------------------------------
# JSON body
# ---------------------------------------------------------------------------

def get_json_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Field validators (shape tier -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body: dict, name: str) -> str:
    if name not in body or body[name] is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    v = body[name]
    if not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return v


def req_int(body: dict, name: str) -> int:
    if name not in body or body[name] is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    v = body[name]
    if not _is_int(v):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return v


def req_num(body: dict, name: str) -> float:
    if name not in body or body[name] is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    v = body[name]
    if not _is_num(v):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    return v


def opt_int(body: dict, name: str, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not _is_int(v):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return v


def opt_num(body: dict, name: str, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not _is_num(v):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    return v


def opt_bool(body: dict, name: str, default=False):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return v


def opt_str(body: dict, name: str, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a string")
    return v


def req_enum(body: dict, name: str, allowed) -> str:
    v = req_str(body, name)
    if v not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return v


# ---------------------------------------------------------------------------
# Date / datetime parsing
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso_date(value, field: str) -> date:
    """Strict YYYY-MM-DD date validation."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be an ISO date YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be a valid calendar date")


def req_iso_date(body: dict, name: str) -> date:
    if name not in body or body[name] is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return parse_iso_date(body[name], name)


def parse_iso_datetime(value, field: str) -> datetime:
    """Parse an ISO 8601 datetime; a trailing Z is accepted. Naive values are
    interpreted as UTC."""
    if not isinstance(value, str) or value == "":
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be an ISO 8601 datetime")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be an ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_iso_datetime(body: dict, name: str) -> datetime:
    if name not in body or body[name] is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return parse_iso_datetime(body[name], name)


def fmt_dt(dt: datetime) -> str:
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
