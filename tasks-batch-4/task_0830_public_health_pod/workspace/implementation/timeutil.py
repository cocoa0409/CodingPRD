"""Logical clock + ISO8601 timestamp helpers.

Every datetime-sensitive rule in the system (credential expiry, inventory-lot
expiration, shift-overlap windows, the "current" throughput variant) is
evaluated against a single server-side logical clock rather than wall-clock
time (PRD 2.5). Only PublicHealthAdmin may advance it via
POST /_clock/set_current_utc; before any such call it reads
2026-03-01T00:00:00Z.
"""
import datetime as dt

from db import db


def _to_utc(d: dt.datetime) -> dt.datetime:
    if d.tzinfo is None:
        return d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def parse_iso8601(value: str) -> dt.datetime:
    """Parse an ISO8601 string (allows trailing 'Z') into an aware UTC datetime."""
    if not isinstance(value, str) or not value:
        raise ValueError("invalid ISO8601 timestamp")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(v)
    return _to_utc(parsed)


def format_iso8601(d: dt.datetime) -> str:
    """Format an aware UTC datetime as ISO8601 with exactly 3 fractional digits and 'Z'."""
    d = _to_utc(d)
    micros = d.microsecond
    millis = micros // 1000
    return d.strftime("%Y-%m-%dT%H:%M:%S") + ".{:03d}Z".format(millis)


def now() -> dt.datetime:
    """Real wall-clock time, used only to mint request ids / not used for business rules."""
    return dt.datetime.now(dt.timezone.utc)


def current_clock() -> dt.datetime:
    """The server's logical clock, used for every business-rule time comparison."""
    return parse_iso8601(db.current_clock_iso)


def current_clock_iso() -> str:
    return format_iso8601(current_clock())


def set_current_clock(iso_str: str):
    parsed = parse_iso8601(iso_str)
    db.current_clock_iso = format_iso8601(parsed)


def new_timestamp_iso() -> str:
    """Timestamp to stamp onto entities (created_at/updated_at/etc): the logical clock."""
    return current_clock_iso()
