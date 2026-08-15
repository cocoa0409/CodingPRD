"""Temporal parsing/formatting helpers.

All temporal fields in this domain are ISO 8601 datetimes. Output timestamps
are ISO 8601 UTC with three fractional digits (PRD 2.4/2.6).
"""
from datetime import datetime, timezone


def parse_datetime(value):
    """Parse an ISO-8601 datetime string to an aware UTC datetime.
    Raises ValueError on malformed input."""
    if isinstance(value, datetime):
        v = value
    elif isinstance(value, str):
        s = value.strip()
        iso = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
        try:
            v = datetime.fromisoformat(iso)
        except ValueError:
            raise ValueError("malformed datetime")
    else:
        raise ValueError("not a datetime value")
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


def fmt_dt(dt):
    """aware datetime -> 'YYYY-MM-DDTHH:MM:SS.mmmZ' (PRD 2.4 timestamp format)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
