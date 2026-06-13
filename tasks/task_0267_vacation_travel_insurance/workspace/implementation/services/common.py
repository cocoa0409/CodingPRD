"""Shared helpers: datetime parsing, pagination, request-body validation."""
from datetime import datetime, timezone

from flask import request

import errors
from db import db


# --------------------------------------------------------------------------
# Datetime handling
# --------------------------------------------------------------------------
def parse_datetime(value):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime.

    Returns None if value is None. Raises ValueError on a malformed string.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def current_clock():
    """The server's logical UTC clock. Falls back to real now if unset."""
    if db.current_clock is not None:
        return db.current_clock
    return datetime.now(timezone.utc)


def to_dt(iso_value):
    """Parse a stored ISO datetime back into a tz-aware datetime (no validation
    errors expected since we control the stored values)."""
    return parse_datetime(iso_value)


def iso_from_dt(dt):
    """Serialize a tz-aware datetime to ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_days(dt, days):
    """Add a whole number of days to a datetime."""
    from datetime import timedelta
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# Body / param helpers
# --------------------------------------------------------------------------
def get_json_body():
    """Return the request JSON body as a dict (empty dict if no body)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.invalid_request("Malformed JSON body.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or not val.strip():
        raise errors.invalid_request(f"Field '{field}' is required and must be a non-empty string.")
    return val


def opt_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field '{field}' must be a string.")
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(f"Field '{field}' must be one of {sorted(allowed)}.")
    return val


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(f"Field '{field}' must be one of {sorted(allowed)}.")
    return val


def require_int(body, field, minimum=None, maximum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field '{field}' is required and must be an integer.")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field '{field}' must be >= {minimum}.")
    if maximum is not None and val > maximum:
        raise errors.invalid_request(f"Field '{field}' must be <= {maximum}.")
    return val


def opt_int(body, field, default=0, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field '{field}' must be an integer.")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field '{field}' must be >= {minimum}.")
    if maximum is not None and val > maximum:
        raise errors.invalid_request(f"Field '{field}' must be <= {maximum}.")
    return val


def opt_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field '{field}' must be a boolean.")
    return val


def require_datetime(body, field):
    val = body.get(field)
    if not isinstance(val, str) or not val.strip():
        raise errors.invalid_request(f"Field '{field}' is required and must be an ISO 8601 datetime.")
    try:
        return parse_datetime(val)
    except Exception:
        raise errors.invalid_request(f"Field '{field}' must be a valid ISO 8601 datetime.")


# --------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0
# --------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("'limit' must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("'offset' must be an integer.")
        if offset < 0:
            raise errors.invalid_request("'offset' must be >= 0.")

    return limit, offset


def paginate(items):
    """items: full filtered+sorted list. Returns (page, limit, offset, total)."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sort_by_created(records):
    """Sort by creation order ascending (created_at, then insertion seq)."""
    return sorted(records, key=lambda r: r["_seq"])
