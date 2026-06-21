"""ISO 8601 parsing/formatting helpers.

PRD §2.4 timestamps use ISO 8601 UTC with three fractional-second digits, but
the framework's regex accepts the form `\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d{1,3})?Z`
so we accept any matching form on input.
"""
import re
from datetime import datetime, timezone


_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$"
)


def is_iso8601(s) -> bool:
    return isinstance(s, str) and bool(_ISO_RE.match(s))


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with optional millisecond precision).
    Returns an aware datetime in UTC. Raises ValueError on bad input.
    """
    if not is_iso8601(s):
        raise ValueError(f"Not a valid ISO 8601 UTC timestamp: {s!r}")
    # `Z` -> +00:00 so fromisoformat handles it on all supported Python versions.
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def diff_minutes_floor(later: datetime, earlier: datetime) -> int:
    """Floor of (later - earlier) in whole minutes. PRD §2.12."""
    delta = (later - earlier).total_seconds()
    return int(delta // 60)
