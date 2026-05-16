"""Shared utility helpers — date parsing, rounding, validation."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from errors import err


# ---------- ISO datetime parsing ----------

def parse_iso_datetime(value, *, field: str = "") -> datetime:
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if value is None:
        raise err("ERR_VALIDATION", f"Field '{field}' is required")
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            raise err("ERR_VALIDATION", f"Field '{field}' must be ISO 8601 datetime")
        # Accept date-only strings and full datetimes; accept trailing Z
        if "T" not in s and len(s) == 10:
            # Date-only — interpret at 00:00:00 UTC
            try:
                d = date.fromisoformat(s)
            except ValueError as e:
                raise err("ERR_VALIDATION", f"Field '{field}' bad date: {e}")
            dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        else:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(s)
            except ValueError as e:
                raise err("ERR_VALIDATION", f"Field '{field}' bad datetime: {e}")
    else:
        raise err("ERR_VALIDATION", f"Field '{field}' must be ISO 8601 datetime, got {type(value).__name__}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_string(dt: datetime) -> str:
    """Render a UTC datetime as YYYY-MM-DDTHH:MM:SS.mmmZ."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------- Month arithmetic ----------

def first_of_month(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, 1, 0, 0, 0, tzinfo=timezone.utc)


def last_of_month(dt: datetime) -> datetime:
    # Move to first of next month, subtract 1 second
    if dt.month == 12:
        nx = datetime(dt.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nx = datetime(dt.year, dt.month + 1, 1, tzinfo=timezone.utc)
    return nx - timedelta(seconds=1)


def add_months(dt: datetime, months: int) -> datetime:
    """Add `months` months to dt; if target month doesn't have the day, clamp to last day of target month."""
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    # Find max day for that month
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    last_day = (nxt - timedelta(days=1)).day
    day = min(dt.day, last_day)
    return datetime(year, month, day, dt.hour, dt.minute, dt.second, dt.microsecond, tzinfo=timezone.utc)


def add_years(dt: datetime, years: int) -> datetime:
    return add_months(dt, years * 12)


def months_between(start: datetime, end: datetime) -> int:
    """Return the integer number of whole months between two datetimes (end >= start expected)."""
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # If the end day is before start day-of-month, we have not yet completed the final month
    if end.day < start.day:
        months -= 1
    return max(0, months)


# ---------- Rounding ----------

def round_half_up_cents(value) -> int:
    """Round a numeric value to the nearest integer with half-up rounding."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------- Validators ----------

MBI_RE = re.compile(r"^[A-Z0-9]{11}$")
STATE_RE = re.compile(r"^[A-Z]{2}$")


def require_field(body: dict, field: str):
    if body is None or field not in body or body[field] is None:
        raise err("ERR_VALIDATION", f"Field '{field}' is required")
    return body[field]


def optional_field(body: dict, field: str, default=None):
    if body is None:
        return default
    if field not in body or body[field] is None:
        return default
    return body[field]


def require_int(v, *, field: str, minimum: int | None = None, maximum: int | None = None) -> int:
    if isinstance(v, bool):
        raise err("ERR_VALIDATION", f"Field '{field}' must be integer")
    if not isinstance(v, int):
        # Reject things like "10" or 10.5
        raise err("ERR_VALIDATION", f"Field '{field}' must be integer")
    if minimum is not None and v < minimum:
        raise err("ERR_VALIDATION", f"Field '{field}' below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise err("ERR_VALIDATION", f"Field '{field}' above maximum {maximum}")
    return v


def require_str(v, *, field: str, max_len: int | None = None, min_len: int = 1) -> str:
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", f"Field '{field}' must be string")
    if len(v) < min_len:
        raise err("ERR_VALIDATION", f"Field '{field}' too short")
    if max_len is not None and len(v) > max_len:
        raise err("ERR_VALIDATION", f"Field '{field}' too long (> {max_len})")
    return v


def require_enum(v, *, field: str, allowed: set) -> str:
    if v not in allowed:
        raise err("ERR_VALIDATION", f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def require_bool(v, *, field: str) -> bool:
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", f"Field '{field}' must be boolean")
    return v


def require_number(v, *, field: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(v, bool):
        raise err("ERR_VALIDATION", f"Field '{field}' must be number")
    if not isinstance(v, (int, float)):
        raise err("ERR_VALIDATION", f"Field '{field}' must be number")
    fv = float(v)
    if minimum is not None and fv < minimum:
        raise err("ERR_VALIDATION", f"Field '{field}' below minimum {minimum}")
    if maximum is not None and fv > maximum:
        raise err("ERR_VALIDATION", f"Field '{field}' above maximum {maximum}")
    return fv


# ---------- Pagination ----------

def parse_pagination(args) -> tuple[int, int]:
    """Extract and validate limit/offset query parameters."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", "limit must be integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", "offset must be integer")
    if limit < 1 or limit > 100:
        raise err("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset < 0:
        raise err("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def paginate(items, limit: int, offset: int) -> tuple[list, dict]:
    """Apply offset/limit slicing and produce pagination meta."""
    total = len(items)
    page = items[offset : offset + limit]
    has_more = offset + len(page) < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }


# ---------- Optimistic concurrency ----------

def check_version(body: dict | None, stored_version: int) -> None:
    """If body contains 'version', ensure it matches stored_version."""
    if not body:
        return
    if "version" in body and body["version"] is not None:
        v = body["version"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise err("ERR_VALIDATION", "version must be integer")
        if v != stored_version:
            raise err("ERR_VERSION_CONFLICT", "Version mismatch")


# ---------- Common system field bookkeeping ----------

def stamp_create(row: dict, *, store_now_iso: str, with_version: bool = True) -> None:
    row["created_at"] = store_now_iso
    if with_version:
        row["updated_at"] = store_now_iso
        row["version"] = 1


def stamp_update(row: dict, *, store_now_iso: str) -> None:
    row["updated_at"] = store_now_iso
    if "version" in row:
        row["version"] = row["version"] + 1
