"""Server-controlled lazy clock.

The server clock can be overridden by the test-driving endpoint
POST /_clock/set_current_utc. All time-gated comparisons read now() from here.
"""
from datetime import datetime, timezone

# When set, this fixed instant is "now". When None, fall back to wall clock.
_override = None  # type: ignore


def set_now(dt):
    """Set the server's current UTC clock to the supplied aware datetime."""
    global _override
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _override = dt.astimezone(timezone.utc)


def now():
    """Return the current UTC instant (override if set, else wall clock)."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def reset():
    """Clear any override (used on a fresh boot)."""
    global _override
    _override = None


def iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    # milliseconds (three fractional digits), trailing 'Z'.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Accepts trailing 'Z' or explicit offset. Raises ValueError on bad input.
    """
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
