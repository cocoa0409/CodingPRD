"""Logical clock (PRD §2.4).

The server boots with the logical clock set to exactly 2026-01-01T00:00:00Z and
before any clock-set call reads exactly this default; it never falls back to
real time for domain comparisons. The clock governs Specimen.collected_at, the
repeat-discount lookback window, and all appointment / analyzer-run comparisons.
"""
from datetime import datetime, timezone, date

CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# Module-level state — reset on every fresh process (per-test-server isolation).
_now = None


def _parse_iso(s):
    """Parse an ISO 8601 string into a timezone-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reset():
    global _now
    _now = _parse_iso(CLOCK_DEFAULT)


def get_now():
    global _now
    if _now is None:
        reset()
    return _now


def set_now(to_iso8601):
    global _now
    _now = _parse_iso(to_iso8601)
    return _now


def now_iso():
    """Logical clock as an ISO 8601 UTC string with three fractional digits."""
    return format_dt(get_now())


def format_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_now_realtime():
    """Envelope timestamp — wall-clock, ISO 8601 UTC, 3 fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    return _parse_iso(s)


def parse_date(s):
    """Parse a YYYY-MM-DD date string."""
    return date.fromisoformat(s.strip())


def derived_age_years(date_of_birth_str):
    """Age in whole years = logical-clock today minus date_of_birth."""
    dob = parse_date(date_of_birth_str)
    today = get_now().date()
    years = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        years -= 1
    return years
