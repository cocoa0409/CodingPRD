"""The server-held logical clock (PRD section 2.5).

Startup value is exactly 2026-08-01T00:00:00Z; the clock never falls back to
wall-clock time.  Instants are carried as naive datetimes understood as UTC.
"""

from datetime import datetime, date, timedelta, timezone

from constants import CLOCK_STARTUP_UTC


def _parse_instant(text):
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(raw), datetime.min.time())
        except ValueError:
            raise ValueError("not an ISO 8601 instant: %r" % text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


_STATE = {"now": _parse_instant(CLOCK_STARTUP_UTC)}


def now():
    return _STATE["now"]


def set_now(instant):
    _STATE["now"] = instant
    return instant


def today():
    return _STATE["now"].date()


def parse_instant(text):
    return _parse_instant(text)


def parse_day(text):
    """Strict ISO calendar date, no time component."""
    return date.fromisoformat(text.strip())


def iso(instant):
    """ISO 8601 UTC with exactly three fractional digits."""
    if instant is None:
        return None
    millis = instant.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        instant.year,
        instant.month,
        instant.day,
        instant.hour,
        instant.minute,
        instant.second,
        millis,
    )


def iso_day(day):
    if day is None:
        return None
    if isinstance(day, datetime):
        day = day.date()
    return "%04d-%02d-%02d" % (day.year, day.month, day.day)


def plus_days(instant, days):
    return instant + timedelta(days=days)


def midnight(day):
    return datetime(day.year, day.month, day.day)
