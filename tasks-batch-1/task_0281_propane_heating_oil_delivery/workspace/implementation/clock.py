"""The logical system clock (PRD §2.10).

Delivery / lease / budget / projection date math all read a single logical
clock set via POST /_clock/set_current_utc. It is ambient (never stored on any
entity). When it has never been set, clock_now falls back to real wall-clock UTC.

Timestamps everywhere in this system are ISO 8601 UTC with exactly three
fractional digits (milliseconds), e.g. "2025-05-24T10:30:00.123Z".
"""
from datetime import datetime, timezone

# The currently-set logical clock instant, as an aware datetime (UTC). None
# until set. In-memory only; wiped on every process boot.
_clock_now = None


def _fmt(dt):
    """Format an aware datetime as ISO 8601 UTC with milliseconds + Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Returns None on failure.
    Naive inputs are treated as UTC.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_real():
    return datetime.now(timezone.utc)


def now_iso_real():
    return _fmt(now_real())


def set_clock(dt):
    global _clock_now
    _clock_now = dt.astimezone(timezone.utc)


def clock_now():
    """Current logical instant as an aware UTC datetime."""
    if _clock_now is not None:
        return _clock_now
    return now_real()


def clock_now_iso():
    return _fmt(clock_now())


def reset():
    global _clock_now
    _clock_now = None
