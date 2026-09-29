"""Logical clock. Nothing in this program is dated from wall-clock time."""

import re
from datetime import datetime, timedelta, timezone

from constants import CLOCK_EPOCH

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"([Zz]|[+-]\d{2}:\d{2})$"
)


def parse_iso(value):
    """Parse a strict ISO-8601 instant. Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    txt = value.strip()
    if txt[-1] in ("Z", "z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def parse_iso_z(value):
    """Parse a strict ISO-8601 instant that must carry a Z (UTC) offset."""
    if not isinstance(value, str):
        return None
    txt = value.strip()
    if not txt or txt[-1] not in ("Z", "z"):
        return None
    return parse_iso(txt)


def format_iso(dt):
    """ISO-8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def format_iso_instant(dt):
    """ISO-8601 UTC at second precision with a trailing Z.

    §2.4 pins three fractional digits on `created_at`/`updated_at` and §2.2 pins
    them on `api_request_timestamp`; every other datetime the API surfaces is a
    dated instant rendered the way §2.5 renders them (`2027-08-11T00:00:00Z`).
    """
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
    )


def add_days(dt, days):
    return dt + timedelta(days=days)


def day_span(later, earlier):
    """Whole 24-hour periods from `earlier` to `later`, floored."""
    delta = later - earlier
    total = delta.total_seconds()
    return int(total // 86400)


class LogicalClock(object):
    def __init__(self):
        self._now = parse_iso(CLOCK_EPOCH)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt.astimezone(timezone.utc)
        return self._now


CLOCK = LogicalClock()


def now():
    return CLOCK.now()
