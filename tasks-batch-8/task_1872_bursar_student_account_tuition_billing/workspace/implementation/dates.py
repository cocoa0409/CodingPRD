"""ISO date helpers. Date fields are stored as canonical YYYY-MM-DD strings."""
from datetime import datetime, date, timezone

from errors import err, ERR_INVALID_REQUEST


def parse_date(v, field="date"):
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"Field must be an ISO date string: {field}")
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"Field must be an ISO date (YYYY-MM-DD): {field}")


def req_date(body, name):
    from response import req_field
    return parse_date(req_field(body, name), name)


def parse_instant(v):
    """Parse an ISO 8601 instant for the logical clock. Date-only -> midnight UTC."""
    if not isinstance(v, str) or not v:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 timestamp string")
    s = v.strip()
    try:
        if len(s) == 10:
            d = datetime.strptime(s, "%Y-%m-%d")
            return d.replace(tzinfo=timezone.utc)
        iso = s.replace("Z", "+00:00") if s.endswith("Z") else s
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 timestamp string")
