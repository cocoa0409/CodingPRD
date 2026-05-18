"""Generic helpers: timestamps, datetime parsing, pagination parsing."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from errors import err
from constants import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)


# -----------------------------------------------------------------------------
# Datetime helpers
# -----------------------------------------------------------------------------
def fmt_iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with 3 fractional digits, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string. Accept trailing Z or +00:00 offsets."""
    if not isinstance(s, str):
        raise err("ERR_VALIDATION", "Timestamp must be a string")
    # Normalise Z -> +00:00 for fromisoformat
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError as exc:
        raise err("ERR_VALIDATION", f"Invalid timestamp: {s}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


# -----------------------------------------------------------------------------
# Calendar quarter helpers
# -----------------------------------------------------------------------------
_QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$")


def parse_quarter_label(label: str):
    """Return (year, quarter_int) or raise."""
    if not isinstance(label, str):
        raise err("ERR_VALIDATION", "quarter_label must be a string")
    m = _QUARTER_RE.match(label)
    if not m:
        raise err("ERR_VALIDATION", "quarter_label must match /^\\d{4}Q[1-4]$/")
    return int(m.group(1)), int(m.group(2))


def quarter_window(label: str):
    """Return (window_start, window_end) datetimes (UTC) for a `YYYYQN` label.

    window_start is UTC midnight on the first day of the quarter (inclusive).
    window_end is UTC midnight on the first day of the FOLLOWING quarter (exclusive).
    """
    year, q = parse_quarter_label(label)
    first_month = 3 * (q - 1) + 1  # 1, 4, 7, 10
    start = datetime(year, first_month, 1, tzinfo=timezone.utc)
    if q == 4:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, first_month + 3, 1, tzinfo=timezone.utc)
    return start, end


def quarter_label_for(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}Q{q}"


def month_key_utc(dt: datetime) -> tuple[int, int]:
    """Return (year, month) tuple for UTC date_trunc('month', dt)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.year, dt.month


# -----------------------------------------------------------------------------
# Pagination
# -----------------------------------------------------------------------------
def parse_pagination(args) -> tuple[int, int]:
    """Read ?limit&offset from query string with defaults; clamp/validate.

    Raises ERR_VALIDATION on non-integer or out-of-range values.
    """
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise err(
                "ERR_VALIDATION",
                f"limit must be in [{PAGINATION_MIN_LIMIT}, {PAGINATION_MAX_LIMIT}]",
            )

    if raw_offset is None or raw_offset == "":
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset must be >= 0")

    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, dict]:
    total = len(items)
    page = items[offset : offset + limit]
    has_more = (offset + limit) < total
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, pagination


# -----------------------------------------------------------------------------
# Body extraction
# -----------------------------------------------------------------------------
def get_body(request) -> dict:
    """Return a dict body or {} if no body. Raise ERR_VALIDATION if non-dict JSON."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False) or {}
    except Exception as exc:
        raise err("ERR_VALIDATION", "Request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def require_field(body: dict, field: str) -> Any:
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", f"Missing required field: {field}")
    return body[field]


def require_str(body: dict, field: str) -> str:
    v = require_field(body, field)
    if not isinstance(v, str) or not v:
        raise err("ERR_VALIDATION", f"Field {field} must be a non-empty string")
    return v


def require_int(body: dict, field: str) -> int:
    v = require_field(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"Field {field} must be an integer")
    return v


def opt_int(body: dict, field: str) -> int | None:
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"Field {field} must be an integer")
    return v
