"""Logical test clock (PRD 2.4).

Every temporal rule in the API reads this clock rather than wall time.  It
defaults to 2026-08-01T00:00:00Z on a fresh boot and can only be moved by
POST /_clock/set_current_utc.
"""

from datetime import datetime, timezone, date

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)


def today():
    return now().date()


def iso(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso(now())


def wall_iso():
    return iso(datetime.now(timezone.utc))


def parse_timestamp(raw):
    """Parse a client supplied ISO 8601 instant.  Returns aware UTC datetime or None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(raw):
    """Parse a YYYY-MM-DD calendar date.  Returns date or None."""
    if not isinstance(raw, str) or len(raw) != 10:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def date_of(raw_or_dt):
    if isinstance(raw_or_dt, datetime):
        return raw_or_dt.astimezone(timezone.utc).date()
    if isinstance(raw_or_dt, date):
        return raw_or_dt
    dt = parse_timestamp(raw_or_dt)
    return dt.date() if dt else None
