"""Datetime helpers — ISO 8601 UTC with three fractional digits.

The marina's logical clock is stored *per-marina* (Marina.current_date), so this
module only provides format/parse helpers and a wall-clock fallback for the
request-id timestamps in the response envelope.
"""
from __future__ import annotations

from datetime import datetime, timezone


def real_now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    """Wall-clock timestamp for `meta.api_request_timestamp`."""
    return iso_format(real_now())


def iso_format(dt: datetime) -> str:
    """Render an aware datetime as ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{ms:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime — accepts trailing 'Z' or explicit offset."""
    if value is None:
        raise ValueError("missing timestamp")
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    v = value.strip()
    if v.endswith("Z") or v.endswith("z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError as exc:
        raise ValueError(f"invalid ISO 8601 timestamp: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
