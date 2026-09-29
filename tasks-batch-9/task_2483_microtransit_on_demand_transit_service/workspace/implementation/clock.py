"""The logical clock (PRD Section 2.5).

Nothing in this service reads the operating-system clock.  Before any call to
POST /_clock/set_current_utc the logical clock reads exactly
2026-08-01T00:00:00Z, and it never falls back to real wall-clock time.

Two rendering styles are used deliberately:

* ``iso_ms`` -- ISO 8601 UTC with exactly three fractional digits.  PRD 2.4
  mandates this for ``created_at`` / ``updated_at``.
* ``fmt_like`` -- renders a computed instant in the same fractional style as the
  instant it was derived from, so an instant echoed or derived from a supplied
  value keeps the caller's precision.
"""
import re
from datetime import datetime, timedelta, timezone

DEFAULT_RAW = "2026-08-01T00:00:00Z"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime; None when invalid."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_state = {"raw": DEFAULT_RAW, "dt": parse_dt(DEFAULT_RAW)}


def now():
    return _state["dt"]


def now_raw():
    return _state["raw"]


def set_now(raw):
    dt = parse_dt(raw)
    _state["raw"] = raw
    _state["dt"] = dt
    return dt


def reset():
    _state["raw"] = DEFAULT_RAW
    _state["dt"] = parse_dt(DEFAULT_RAW)


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def iso_s(dt):
    """ISO 8601 UTC at second precision."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
    )


def fmt_like(dt, reference_raw):
    """Render ``dt`` using the fractional style of ``reference_raw``."""
    if dt is None:
        return None
    if isinstance(reference_raw, str) and "." in reference_raw:
        return iso_ms(dt)
    return iso_s(dt)


def iso_now_ms():
    return iso_ms(now())


def date_of(dt):
    """UTC calendar date (YYYY-MM-DD) of an instant."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)


def week_start_of(dt):
    """Monday (YYYY-MM-DD) anchoring the ISO week the instant falls in."""
    dt = dt.astimezone(timezone.utc)
    monday = dt - timedelta(days=dt.weekday())
    return "%04d-%02d-%02d" % (monday.year, monday.month, monday.day)


def week_start_of_date_string(date_string):
    dt = parse_dt(date_string + "T00:00:00Z")
    return week_start_of(dt) if dt else None


def is_date_string(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    return parse_dt(value + "T00:00:00Z") is not None


def plus_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def date_string_of_raw(raw):
    dt = parse_dt(raw)
    return date_of(dt) if dt is not None else None
