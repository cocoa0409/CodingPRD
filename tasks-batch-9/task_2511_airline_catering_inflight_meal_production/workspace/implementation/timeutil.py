"""ISO 8601 UTC parsing and rendering helpers.

PRD 2.5: every server-written timestamp is an ISO 8601 UTC instant with three
fractional digits.  ProductionBatch.release_deadline_utc is the single value the
scaffold pins to whole seconds (rendered with a trailing Z).
"""

from datetime import datetime, timezone, timedelta
import re

UTC = timezone.utc

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_instant(value):
    """Parse an ISO 8601 UTC instant.  Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    off = dt.utcoffset()
    if off is None or off != timedelta(0):
        # Every instant in this service is expressed in UTC.
        return None
    return dt.astimezone(UTC)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date.  Returns a date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_ms(dt):
    """Render an instant with three fractional digits and a trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_sec(dt):
    """Render an instant truncated to whole seconds with a trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC).replace(microsecond=0)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
    )


def minutes(n):
    return timedelta(minutes=n)


def hours(n):
    return timedelta(hours=n)
