"""Logical clock (PRD 2.4).

The server keeps a single logical UTC instant, initialised to 2026-08-01T00:00:00Z on
every boot.  It is what every ``*_at`` stamp, the 60-day documentation window, the
730-day cooling-off gate, the corrective-action due-date check and the lateness penalty
in remediation scoring are measured against.  ``POST /_clock/set_current_utc`` replaces
it; that call mutates no entity and bumps no version.
"""

from datetime import datetime, timedelta, timezone, date

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

_state = {"now": None}


def reset():
    _state["now"] = parse_instant(DEFAULT_CLOCK)


def parse_instant(raw):
    """Parse an ISO-8601 UTC instant.  Returns a naive-UTC datetime or None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def parse_date(raw):
    """Parse a YYYY-MM-DD calendar date.  Returns a date or None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def format_instant(value):
    """ISO 8601 UTC with exactly three fractional-second digits and a trailing Z."""
    if value is None:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def now():
    if _state["now"] is None:
        reset()
    return _state["now"]


def now_iso():
    return format_instant(now())


def today():
    """The calendar date of the logical clock."""
    return now().date()


def set_now(value):
    _state["now"] = value


def days_between(later, earlier):
    """Whole days from ``earlier`` to ``later`` (may be negative)."""
    return (later - earlier).days


def add_days(value, count):
    return value + timedelta(days=count)


reset()
