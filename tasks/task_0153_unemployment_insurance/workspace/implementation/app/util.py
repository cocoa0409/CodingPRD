"""Shared utilities: ID generation, ISO 8601 formatting, date helpers."""
from __future__ import annotations

import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional


_ALPHANUM = string.ascii_uppercase + string.digits


def new_id() -> str:
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """req_ prefix + 20 alphanum chars per PRD §2.2."""
    suffix = "".join(random.choices(_ALPHANUM, k=20))
    return f"req_{suffix}"


def format_iso8601(dt: datetime) -> str:
    """ISO 8601 UTC timestamp with three fractional digits, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def parse_iso8601(s: str) -> Optional[datetime]:
    """Lenient ISO 8601 datetime parser; accepts trailing Z."""
    if not isinstance(s, str):
        return None
    s2 = s.strip()
    if not s2:
        return None
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(s: str) -> Optional[date]:
    """Parse YYYY-MM-DD into a date."""
    if not isinstance(s, str) or len(s) != 10:
        return None
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def format_iso_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def quarter_of_month(month: int) -> int:
    """Return 1..4 from a 1..12 month."""
    return (month - 1) // 3 + 1


def quarter_start_month(q: int) -> int:
    """Return the first month (1, 4, 7, 10) of the given quarter."""
    return (q - 1) * 3 + 1


def add_quarters(year: int, quarter: int, delta: int) -> tuple[int, int]:
    """Add `delta` quarters to (year, quarter); returns (year, quarter)."""
    total = (year * 4 + (quarter - 1)) + delta
    new_year = total // 4
    new_q = total % 4 + 1
    return new_year, new_q


def first_sunday_on_or_before(d: date) -> date:
    """Return the first Sunday on or before the given date (ISO weekday 7 == Sunday)."""
    # Python weekday(): Monday=0..Sunday=6.
    # Sunday is weekday() == 6.
    # We want the most recent Sunday including d itself.
    delta = (d.weekday() - 6) % 7
    return d - timedelta(days=delta)


def add_days(d: date, days: int) -> date:
    return d + timedelta(days=days)
