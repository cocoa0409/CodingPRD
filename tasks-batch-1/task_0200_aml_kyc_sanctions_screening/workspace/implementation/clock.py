"""Server-controlled logical clock (PRD §2.9).

Time-dependent computations and any "current time" the server needs are read
from this logical clock rather than wall-clock time. A PlatformAdmin may set the
current UTC instant via POST /_clock/set_current_utc with a to_iso8601 value.

Note: created_at/updated_at/api_request_timestamp are server-minted "now"
timestamps. The PRD only ties the *logical clock* to periodic-review due dates and
filing deadlines; it also says the clock provides "any 'current time' the server
needs". We therefore source all server-minted timestamps from this clock so that
test-driven time advances deterministically affect created_at where relevant.
"""

from datetime import datetime, timezone

# Module-level singleton override; None means use wall clock.
_override = None


def reset():
    global _override
    _override = None


def set_current_utc(iso_str):
    """Set the logical clock from an ISO 8601 string."""
    global _override
    _override = parse_iso8601(iso_str)


def now():
    """Current UTC datetime per the logical clock."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def now_iso():
    """Current logical-clock instant as ISO 8601 UTC, millisecond precision."""
    return format_iso8601(now())


def format_iso8601(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso8601(s):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
