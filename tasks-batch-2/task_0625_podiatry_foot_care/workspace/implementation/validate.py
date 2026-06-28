"""Structural body validation helpers (PRD §2.7, validation priority 5).

Raises ApiError(ERR_INVALID_REQUEST, 422) on any structural violation.
"""

import re
from datetime import datetime

import errors

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def require(body, field):
    """Field must be present (not None)."""
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    return body[field]


def as_str(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {field}")
        return default
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field {field} must be a non-empty string")
    return val


def as_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean")
    return val


def as_int(body, field, required=True, default=None, minimum=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {field}")
        return default
    val = body[field]
    # bool is a subclass of int; reject it as an integer value.
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}")
    return val


def as_number(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {field}")
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field {field} must be a number")
    return val


def as_enum(body, field, allowed, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {field}")
        return default
    val = body[field]
    if val not in allowed:
        raise errors.invalid_request(
            f"Field {field} must be one of {sorted(allowed)}")
    return val


def as_date(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {field}")
        return default
    val = body[field]
    if not isinstance(val, str) or not _DATE_RE.match(val):
        raise errors.invalid_request(f"Field {field} must be an ISO date (YYYY-MM-DD)")
    try:
        datetime.strptime(val, "%Y-%m-%d")
    except ValueError:
        raise errors.invalid_request(f"Field {field} is not a valid calendar date")
    return val


def parse_datetime(value):
    """Parse an ISO 8601 datetime string into a timezone-aware datetime.

    Accepts a trailing 'Z' (UTC). Naive values are treated as UTC.
    """
    if not isinstance(value, str):
        raise errors.invalid_request("Datetime must be a string")
    raw = value
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise errors.invalid_request("Invalid ISO 8601 datetime")
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def as_datetime(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {field}")
        return None
    return parse_datetime(body[field])
