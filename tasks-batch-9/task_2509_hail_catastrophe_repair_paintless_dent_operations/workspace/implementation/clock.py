"""The logical clock (PRD §2.4).

At server startup the logical clock reads exactly 2026-08-01T00:00:00Z and holds
that value until it is explicitly moved; the service never falls back to real time.
"""

from datetime import datetime, timezone, timedelta

DEFAULT_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def format_audit_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.5)."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def format_instant(dt):
    """A full ISO 8601 UTC instant as the logical clock holds it (PRD §2.4).

    Instant-typed fields are "taken from the logical clock", so they render the
    clock's own instant: the fractional part appears only when the clock carries
    sub-second precision.
    """
    dt = dt.astimezone(timezone.utc)
    head = "%04d-%02d-%02dT%02d:%02d:%02d" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
    )
    if dt.microsecond:
        return "%s.%03dZ" % (head, dt.microsecond // 1000)
    return head + "Z"


def parse_instant(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
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
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_date(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_INSTANT

    def reset(self):
        self._now = DEFAULT_INSTANT

    def set(self, dt):
        self._now = dt.astimezone(timezone.utc)

    def now(self):
        return self._now

    def instant(self):
        """Current logical instant, formatted."""
        return format_instant(self._now)

    def date(self):
        """The calendar date of the logical clock instant in UTC."""
        return self._now.date()

    def date_str(self):
        return format_date(self._now.date())

    def plus_days(self, days):
        return self._now + timedelta(days=days)


clock = LogicalClock()
