"""Shared helpers for record lifecycle: common fields, parsing, validation."""

import re
from datetime import datetime, timezone, date

from db import new_id, iso_ts, CLOCK
from errors import invalid_request


def new_common():
    """Return the standard common-field dict for a primary resource (§2.5)."""
    now = iso_ts(CLOCK.now())
    return {"id": new_id(), "created_at": now, "updated_at": now, "version": 1}


def new_ledger():
    """Append-only ledger records carry only id and created_at (§2.5)."""
    return {"id": new_id(), "created_at": iso_ts(CLOCK.now())}


def touch(record):
    """Refresh updated_at and increment version."""
    record["updated_at"] = iso_ts(CLOCK.now())
    record["version"] = record.get("version", 1) + 1


def touch_no_version(record):
    record["updated_at"] = iso_ts(CLOCK.now())


def require_field(body, name):
    v = body.get(name)
    if v is None:
        raise invalid_request(f"Missing required field: {name}")
    return v


def require_string(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or v == "":
        raise invalid_request(f"Field {name} must be a non-empty string")
    return v


def require_int(body, name, minimum=None, maximum=None):
    v = require_field(body, name)
    if not isinstance(v, int) or isinstance(v, bool):
        raise invalid_request(f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise invalid_request(f"Field {name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise invalid_request(f"Field {name} must be <= {maximum}")
    return v


def require_enum(body, name, allowed):
    v = require_field(body, name)
    if v not in allowed:
        raise invalid_request(f"Field {name} must be one of {sorted(allowed)}")
    return v


def optional_int(body, name, minimum=None, maximum=None):
    if name not in body or body.get(name) is None:
        return None
    return require_int(body, name, minimum=minimum, maximum=maximum)


def parse_iso_datetime(value):
    """Parse an ISO 8601 datetime into an aware datetime (UTC assumed when naive)."""
    if not isinstance(value, str):
        raise invalid_request("Expected an ISO 8601 datetime string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise invalid_request(f"Invalid ISO 8601 datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso_date(value, field="date"):
    """Parse an ISO date (YYYY-MM-DD) into a datetime.date."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise invalid_request(f"Field {field} must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise invalid_request(f"Field {field} must be an ISO date (YYYY-MM-DD)")


def validate_date_string(value, field):
    """Validate that value is an ISO date string; return the parsed date."""
    return parse_iso_date(value, field)


def cmp_dates(a, b):
    """Compare two ISO date strings; returns -1, 0, 1. None term_date means +inf."""
    if a is None and b is None:
        return 0
    if a is None:
        return 1
    if b is None:
        return -1
    if a < b:
        return -1
    if a > b:
        return 1
    return 0
