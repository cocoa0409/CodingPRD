"""Shared helpers: capability ordering, datetime parsing, age, pagination, serialization."""
import math
from datetime import datetime, timezone, date

from errors import ApiError, ERR_INVALID_REQUEST, err

# Capability ladder (PRD §2.7): TRAIL < UTILITY < MOUNTAIN.
CLASS_RANK = {"TRAIL": 0, "UTILITY": 1, "MOUNTAIN": 2}


def class_rank(value):
    return CLASS_RANK[value]


# ---------------------------------------------------------------------------
# Datetime parsing
# ---------------------------------------------------------------------------
def parse_datetime(value):
    """Parse an ISO 8601 instant (accepts trailing Z). Returns aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO 8601 calendar date (YYYY-MM-DD)."""
    if not isinstance(value, str):
        raise ValueError("not a date string")
    return date.fromisoformat(value.strip())


def age_at(dob_value, at_dt):
    """Whole-year age of a person born on dob (date) at the instant at_dt (datetime)."""
    dob = parse_date(dob_value)
    at = at_dt.date()
    years = at.year - dob.year
    # Subtract one if the birthday has not yet occurred this year.
    if (at.month, at.day) < (dob.month, dob.day):
        years -= 1
    return years


# ---------------------------------------------------------------------------
# Request body field validation (ERR_INVALID_REQUEST, priority 5)
# ---------------------------------------------------------------------------
def require_field(body, name):
    if name not in body or body[name] is None:
        err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return body[name]


def require_str(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or v == "":
        err(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return v


def require_int(body, name, minimum=None):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return v


def require_number(body, name, minimum=None, maximum=None, exclusive_min=None):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    if minimum is not None and v < minimum:
        err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    if exclusive_min is not None and v <= exclusive_min:
        err(ERR_INVALID_REQUEST, f"Field {name} must be > {exclusive_min}")
    if maximum is not None and v > maximum:
        err(ERR_INVALID_REQUEST, f"Field {name} must be <= {maximum}")
    return v


def require_enum(body, name, allowed):
    v = require_field(body, name)
    if v not in allowed:
        err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return v


def require_datetime(body, name):
    v = require_field(body, name)
    try:
        return parse_datetime(v)
    except Exception:
        err(ERR_INVALID_REQUEST, f"Field {name} must be an ISO 8601 datetime")


def optional_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if v not in allowed:
        err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination(args):
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by creation order, then slice. Returns (page, pagination_meta)."""
    ordered = sorted(items, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
