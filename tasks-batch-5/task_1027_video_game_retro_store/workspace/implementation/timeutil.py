"""Datetime parsing / formatting helpers.

All instants in the system are ISO 8601 UTC. Server-minted timestamps
(created_at, updated_at, api_request_timestamp) use wall-clock time with three
fractional digits (PRD 2.4). Time-sensitive business logic (rental late fees,
tournament registration windows) is driven by the logical clock, never wall
time (PRD 2.10).
"""
from datetime import datetime, timezone


def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_iso():
    """Wall-clock UTC timestamp, ISO 8601 with exactly three fractional digits."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
