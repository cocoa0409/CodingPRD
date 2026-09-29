"""The server-held logical clock (PRD 2.4).

Nothing in this system reads wall-clock time: creation timestamps, day
arithmetic and the response envelope timestamp all read this clock.
"""
import re
from datetime import datetime, timedelta, timezone

import config

_RFC3339_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class LogicalClock:
    def __init__(self):
        self.reset()

    def reset(self):
        self._now = parse_datetime(config.CLOCK_INITIAL)

    def now(self):
        return self._now

    def set(self, value):
        self._now = value

    def date(self):
        return self._now.date()

    def iso(self):
        return format_datetime(self._now)


def parse_datetime(text):
    """Strict RFC3339-with-Z parse. Returns None when malformed."""
    if not isinstance(text, str) or not _RFC3339_Z.match(text):
        return None
    body = text[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000000")[:6]
        body = head + "." + frac
        fmt = "%Y-%m-%dT%H:%M:%S.%f"
    else:
        fmt = "%Y-%m-%dT%H:%M:%S"
    try:
        return datetime.strptime(body, fmt).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_date(text):
    """Strict YYYY-MM-DD parse. Returns None when malformed."""
    if not isinstance(text, str) or not _ISO_DATE.match(text):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_datetime(value):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        "%03d" % (value.microsecond // 1000)
    ) + "Z"


def format_date(value):
    return value.isoformat() if value is not None else None


def days_between(later, earlier):
    """Whole days between two datetimes (floor)."""
    return int((later - earlier).total_seconds() // 86400)


def add_days(value, days):
    return value + timedelta(days=days)


clock = LogicalClock()
