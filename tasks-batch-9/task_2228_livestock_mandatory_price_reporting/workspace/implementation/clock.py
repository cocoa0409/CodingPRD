"""The program's logical clock (PRD §2.4).

Before the clock has ever been set it reads exactly 2026-08-01T00:00:00Z.
The server never falls back to wall-clock time for any temporal evaluation.
"""

from datetime import datetime, timezone

DEFAULT_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = DEFAULT_INSTANT


def now():
    """Current logical instant as a timezone-aware UTC datetime."""
    return _current


def set_now(instant):
    global _current
    _current = instant.astimezone(timezone.utc)
    return _current


def reset():
    global _current
    _current = DEFAULT_INSTANT


def iso_millis(instant):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    dt = instant.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_now():
    return iso_millis(_current)


def parse_iso(value):
    """Parse an ISO 8601 datetime string. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
