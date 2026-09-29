"""Timestamp parsing and formatting.

Domain instants are whole seconds in UTC with a trailing Z (PRD 2.9/2.10).
Audit stamps (created_at / updated_at) carry exactly three fractional digits.
"""
import re
from datetime import datetime, timedelta, timezone

RFC3339_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?[Zz]$"
)


def is_timestamp(value):
    return isinstance(value, str) and RFC3339_RE.match(value) is not None and parse(value) is not None


def parse(value):
    """Parse an RFC3339 UTC timestamp with trailing Z into an aware datetime.

    Returns None when the value is not a valid timestamp.
    """
    if not isinstance(value, str):
        return None
    m = RFC3339_RE.match(value)
    if not m:
        return None
    frac = m.group(7) or ""
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def sec(value):
    """Parse to second granularity (every datetime comparison is at second granularity)."""
    dt = parse(value) if isinstance(value, str) else value
    if dt is None:
        return None
    return dt.replace(microsecond=0)


def fmt(dt):
    """Format a datetime as a whole-second UTC instant."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ms(dt):
    """Format a datetime with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_audit():
    return fmt_ms(datetime.now(timezone.utc))


def delta_seconds(a, b):
    """Whole seconds from a to b (both strings or datetimes)."""
    da, db = sec(a), sec(b)
    return int((db - da).total_seconds())


def plus(value, seconds):
    return fmt(sec(value) + timedelta(seconds=seconds))
