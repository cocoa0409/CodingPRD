"""Shared validation, pagination, lookup, and date helpers."""
from datetime import date, datetime, timezone

from flask import request

from db import db
from errors import err

# Ordinal level ladder (PRD 3.1): PETITE < NOVICE < INTERMEDIATE < ADVANCED < ELITE
LEVELS = ["PETITE", "NOVICE", "INTERMEDIATE", "ADVANCED", "ELITE"]
LEVEL_ORDINAL = {lvl: i for i, lvl in enumerate(LEVELS)}

DISCIPLINES = {"BALLET", "JAZZ", "TAP", "HIPHOP", "CONTEMPORARY", "ACRO"}
SIZE_CODES = {"CHILD_S", "CHILD_M", "CHILD_L", "ADULT_S", "ADULT_M", "ADULT_L"}
ATTENDANCE_RESULTS = {"PRESENT", "ABSENT_EXCUSED", "ABSENT_UNEXCUSED"}

# Number of days immediately preceding the makeup session's date within which
# the cited absence must fall (PRD 3.5; constant named MAKEUP_WINDOW_DAYS).
MAKEUP_WINDOW_DAYS = 30


# --------------------------------------------------------------------------
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------
def paginate(items):
    """items is an already-sorted list of resources. Returns (page, pagination_meta)."""
    limit = _int_param("limit", default=10, lo=1, hi=100)
    offset = _int_param("offset", default=0, lo=0, hi=None)
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


def _int_param(name, default, lo, hi):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"Query param {name} must be an integer.")
    if lo is not None and val < lo:
        raise err("ERR_INVALID_REQUEST", f"Query param {name} below minimum {lo}.")
    if hi is not None and val > hi:
        raise err("ERR_INVALID_REQUEST", f"Query param {name} above maximum {hi}.")
    return val


def sort_by_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# Existence (PRD 2.7) — ERR_NOT_FOUND
# --------------------------------------------------------------------------
def lookup(table, _id):
    res = table.get(_id)
    if res is None:
        raise err("ERR_NOT_FOUND", "Resource not found.")
    return res


# --------------------------------------------------------------------------
# Body field validation (ERR_INVALID_REQUEST)
# --------------------------------------------------------------------------
def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {n}.")


def require_str(body, name, allow_empty=False):
    v = body.get(name)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a string.")
    if not allow_empty and v.strip() == "":
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be non-empty.")
    return v


def require_int(body, name, lo=None, hi=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer.")
    if lo is not None and v < lo:
        raise err("ERR_INVALID_REQUEST", f"Field {name} below minimum {lo}.")
    if hi is not None and v > hi:
        raise err("ERR_INVALID_REQUEST", f"Field {name} above maximum {hi}.")
    return v


def optional_int(body, name, default, lo=None, hi=None):
    if name not in body or body[name] is None:
        return default
    return require_int(body, name, lo=lo, hi=hi)


def require_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean.")
    return v


def require_enum(body, name, allowed):
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(allowed)}.")
    return v


# --------------------------------------------------------------------------
# Date / datetime parsing
# --------------------------------------------------------------------------
def parse_date(body, name):
    """Parse an ISO 8601 date (YYYY-MM-DD) into a date object."""
    v = body.get(name)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an ISO date string.")
    try:
        return date.fromisoformat(v[:10])
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"Field {name} is not a valid ISO date.")


def parse_datetime(body, name):
    """Parse an ISO 8601 datetime into an aware UTC datetime."""
    v = body.get(name)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an ISO datetime string.")
    return parse_iso_datetime(v)


def parse_iso_datetime(v):
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Not a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_date():
    return db.clock.date()
