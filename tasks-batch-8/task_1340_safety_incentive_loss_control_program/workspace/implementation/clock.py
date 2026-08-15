"""Logical clock (PRD section 2.5).

Starts at exactly 2026-08-01T00:00:00Z on every boot and never falls back to
wall-clock time. Advanced only via POST /_clock/set_current_utc. Every temporal
rule in the program reads this clock and nothing else.
"""

from datetime import datetime, date, timezone

_DEFAULT = "2026-08-01T00:00:00Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if isinstance(s, datetime):
        dt = s
    elif isinstance(s, str):
        v = s.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
    else:
        raise ValueError("not an ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse an ISO 8601 calendar date (YYYY-MM-DD)."""
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, str):
        return date.fromisoformat(s.strip())
    raise ValueError("not an ISO 8601 date")


def fmt(dt):
    """Whole-second ISO 8601 UTC rendering used for business datetime fields."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ms(dt):
    """Three-fractional-digit ISO 8601 UTC rendering (created_at / updated_at /
    envelope meta; PRD sections 2.2 and 2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class _Clock:
    def __init__(self):
        self._now = parse_iso(_DEFAULT)

    def now(self):
        return self._now

    def today(self):
        return self._now.date()

    def set(self, value):
        self._now = parse_iso(value)
        return self._now


CLOCK = _Clock()
