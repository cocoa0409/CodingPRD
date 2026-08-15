"""Program-year logical clock (PRD section 2.5).

All deadline arithmetic and all system-stamped timestamps are driven by this
clock, never by wall-clock time. Before any operator intervention the clock
reads 2026-08-01T00:00:00Z and it never falls back to wall-clock time.
"""

from datetime import datetime, timezone

_DEFAULT_RAW = "2026-08-01T00:00:00Z"

_current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_current_raw = _DEFAULT_RAW


def now():
    return _current


def set_current(dt, raw):
    global _current, _current_raw
    _current = dt
    _current_raw = raw


def current_raw():
    return _current_raw


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD section 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
