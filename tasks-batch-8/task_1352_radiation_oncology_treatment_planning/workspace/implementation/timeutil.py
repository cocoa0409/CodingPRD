"""Timestamp and datetime helpers.

- created_at / updated_at: real UTC wall-clock, ISO 8601 with three fractional
  digits and a Z suffix (PRD section 2.4).
- Logical clock: maintained separately (store.clock); starts at exactly
  2026-08-01T00:00:00Z and is only consulted by the machine-down cascade.
"""
import re
import uuid
from datetime import datetime, timezone, date

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now_iso():
    """Wall-clock UTC timestamp with exactly three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def new_req_id():
    return "req_" + uuid.uuid4().hex[:24]


def parse_datetime(s):
    """Parse an ISO 8601 datetime into an aware UTC datetime, or None."""
    if not isinstance(s, str) or not s.strip():
        return None
    txt = s.strip()
    try:
        if txt.endswith(("Z", "z")):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse an ISO 8601 calendar date (YYYY-MM-DD), or None."""
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        return None


def fmt_clock(dt):
    """Canonical rendering of the logical clock: seconds precision, Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def is_weekend_dt(dt):
    """True when the UTC instant falls on a Saturday or Sunday."""
    return dt.weekday() >= 5
