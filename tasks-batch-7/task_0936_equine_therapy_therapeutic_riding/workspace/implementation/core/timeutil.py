"""The single timestamp producer for the whole API (PRD §2.5).

Four rendering classes, and nothing outside this module ever formats an instant:

  1. server-minted   -> YYYY-MM-DDTHH:MM:SS.mmmZ        (minted())
  2. caller-supplied -> echoed BYTE-FOR-BYTE            (echoed())
  3. server-derived  -> YYYY-MM-DDTHH:MM:SS.mmmZ        (derived() == minted())
  4. date-only       -> YYYY-MM-DD, echoed byte-for-byte (plain strings)

`hold_release_at` and `certification_expires_at` deliberately switch class
mid-life: they start echoed (class 2) and are re-stamped derived (class 3).
Because both classes are carried by the same TS object, switching class is just
replacing the object.
"""

import re
from datetime import datetime, timedelta, timezone

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

UTC = timezone.utc


class TS:
    """An instant plus the exact string the API must render for it."""

    __slots__ = ("raw", "dt")

    def __init__(self, raw, dt):
        self.raw = raw
        self.dt = dt

    def __repr__(self):  # pragma: no cover - debugging aid
        return "TS(%r)" % (self.raw,)


def fmt_minted(dt):
    """Class 1 / class 3 rendering: exactly three fractional digits, trailing Z."""
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def minted(dt):
    """Class 1 (server-minted) and class 3 (server-derived) instants."""
    dt = dt.astimezone(UTC)
    return TS(fmt_minted(dt), dt)


derived = minted


def parse_instant(value):
    """Parse an ISO-8601 instant.  Returns an aware UTC datetime or None."""
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
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def echoed(value):
    """Class 2: store the caller's string verbatim, keep the parsed instant."""
    dt = parse_instant(value)
    if dt is None:
        return None
    return TS(value, dt)


def parse_date(value):
    """Parse a YYYY-MM-DD date-only string.  Returns a date or None."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def date_to_instant(d):
    """§2.5: a date-only value promoted to that calendar date at 00:00:00.000Z."""
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def plus_days(dt, days):
    return dt + timedelta(days=days)


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


def plus_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def day_of(dt):
    """Calendar (UTC) date of an instant."""
    return dt.astimezone(UTC).date()


def date_str(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def week_start(d):
    """The MONDAY on or before date d."""
    return d - timedelta(days=d.weekday())


def raw_or_none(ts):
    return ts.raw if ts is not None else None


def dt_or_none(ts):
    return ts.dt if ts is not None else None
