"""Time helpers: ISO 8601 UTC rendering/parsing and the logical clock.

PRD §2.4: created_at/updated_at are ISO 8601 UTC with three fractional digits.
PRD §2.5: time-dependent rules read a logical clock pinned at startup to
exactly 2026-08-01T00:00:00Z, moved only by POST /api/_clock/set_current_utc.
Input datetimes are echoed verbatim on output; a parsed copy drives comparisons.
"""
import secrets
from datetime import datetime, timezone

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now_iso():
    """Wall-clock UTC timestamp, three fractional digits, Z suffix."""
    return iso_ms(datetime.now(timezone.utc))


def iso_ms(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware datetime (UTC assumed
    when the offset is omitted). Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def new_request_id():
    return "req_" + secrets.token_hex(12)
