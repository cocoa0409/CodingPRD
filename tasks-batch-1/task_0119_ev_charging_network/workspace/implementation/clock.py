"""Server clock.

The server keeps a mutable "current UTC" used for time-gated transitions
(reservation windows, tariff effectivity, no-show). It can be set via
POST /api/_clock/set_current_utc (PRD §3.9). When never set, it tracks real
wall-clock UTC.

Timestamps are ISO 8601 UTC with exactly three fractional digits (PRD §2.4).
"""
import datetime

_overridden_now = None  # datetime (tz-aware UTC) or None


def _real_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def set_now(dt):
    global _overridden_now
    _overridden_now = dt


def current_utc():
    """Return the current server UTC as a tz-aware datetime."""
    if _overridden_now is not None:
        return _overridden_now
    return _real_utc()


def fmt(dt):
    """Format a tz-aware datetime as ISO8601 UTC with 3 fractional digits + Z."""
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def now_iso():
    return fmt(current_utc())


def parse_iso(s):
    """Parse an ISO8601 datetime string into a tz-aware UTC datetime.

    Accepts trailing 'Z' and optional fractional seconds / offsets.
    Naive datetimes are assumed to be UTC.
    """
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    text = s.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)
