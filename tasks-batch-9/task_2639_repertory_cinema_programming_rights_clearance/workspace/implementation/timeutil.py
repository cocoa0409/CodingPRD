"""Instant / date / venue-local time helpers.

All instants that cross the wire are ISO 8601 UTC with exactly three
fractional digits (PRD 2.0).  Venue-local dates and times are derived from a
UTC instant by adding venue.utc_offset_minutes (PRD 2.8); no DST arithmetic.
"""
from datetime import datetime, timezone, timedelta, date, time

UTC = timezone.utc


def parse_instant(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_instant(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def parse_day(value):
    """Parse a YYYY-MM-DD calendar date.  Returns a date or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if len(s) != 10:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def fmt_day(d):
    return None if d is None else d.isoformat()


def parse_hhmm(value):
    """Parse a venue-local HH:MM string into minutes past midnight, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if len(s) != 5 or s[2] != ":":
        return None
    try:
        hh = int(s[0:2])
        mm = int(s[3:5])
    except ValueError:
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh * 60 + mm


def local_naive(dt, offset_minutes):
    """The venue-local wall clock reading of a UTC instant (naive datetime)."""
    return dt.astimezone(UTC).replace(tzinfo=None) + timedelta(minutes=offset_minutes or 0)


def local_day(dt, offset_minutes):
    return local_naive(dt, offset_minutes).date()


def local_minutes(dt, offset_minutes):
    ln = local_naive(dt, offset_minutes)
    return ln.hour * 60 + ln.minute


def from_local_naive(ln, offset_minutes):
    """Inverse of local_naive: venue-local wall clock -> UTC instant."""
    return (ln - timedelta(minutes=offset_minutes or 0)).replace(tzinfo=UTC)


def local_day_start_instant(d, offset_minutes):
    return from_local_naive(datetime.combine(d, time(0, 0)), offset_minutes)


def iso_week_key(dt, offset_minutes):
    """The venue-local Monday date of the ISO week containing this instant."""
    d = local_day(dt, offset_minutes)
    return d - timedelta(days=d.weekday())


def whole_minutes(delta):
    return int(delta.total_seconds() // 60)
