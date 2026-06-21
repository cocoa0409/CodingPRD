"""Datetime parsing for input fields (counted_at, expected_at, tapped_from,
tapped_until, sold_at, _clock to_iso8601). All such inputs are ISO 8601
strings; we parse to timezone-aware UTC datetimes for comparison."""
from datetime import datetime, timezone

from errors import invalid_request


def parse_iso(value, field_name):
    if not isinstance(value, str):
        raise invalid_request("{} must be an ISO 8601 datetime string.".format(field_name))
    s = value.strip()
    if not s:
        raise invalid_request("{} must be a non-empty ISO 8601 datetime string.".format(field_name))
    raw = s
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise invalid_request("{} is not a valid ISO 8601 datetime.".format(field_name))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
