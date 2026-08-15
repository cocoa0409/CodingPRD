"""Deterministic logical clock (PRD 2.4).

The clock NEVER falls back to wall-clock. Startup value is exactly
2026-05-01T00:00:00Z. All time-dependent behaviour (age gating, retention
expiry, scan scheduling, sweep deadlines) is evaluated against this clock.
"""

from datetime import datetime, timezone

CLOCK = {"now": "2026-05-01T00:00:00Z"}


def parse_iso(iso):
    """Parse an ISO 8601 string into an aware UTC datetime.

    Raises ValueError/TypeError on unparseable input. Naive inputs are
    assumed UTC. Aware inputs are converted to UTC.
    """
    if not isinstance(iso, str):
        raise ValueError("not an ISO 8601 string")
    text = iso.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_iso(dt):
    """Render an aware UTC datetime with exactly three fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def get_now():
    """Current logical-clock instant as an aware UTC datetime."""
    return parse_iso(CLOCK["now"])


def set_now(iso):
    """Advance the logical clock to `iso`. Returns the normalized current UTC.

    Raises ValueError when `iso` does not parse as ISO 8601.
    """
    dt = parse_iso(iso)
    CLOCK["now"] = format_iso(dt)
    return CLOCK["now"]
