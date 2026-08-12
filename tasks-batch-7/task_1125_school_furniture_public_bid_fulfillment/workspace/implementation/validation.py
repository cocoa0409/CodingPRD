"""Shared validation helpers: existence (priority 4), request shape (priority 5),
pagination parsing, and date arithmetic."""
from datetime import date, datetime, timedelta

from flask import request

from db import store
from errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND, raise_err


# ---------------------------------------------------------------- existence

def get_or_404(collection, rid, label="resource"):
    rec = collection.get(rid) if isinstance(rid, str) else None
    if rec is None:
        raise_err(ERR_NOT_FOUND, f"{label} not found: {rid}")
    return rec


def check_fk(collection, value, label):
    """Body FK existence: only string ids can resolve; non-strings fall to shape."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None  # shape stage will reject the type
    return get_or_404(collection, value, label)


# ---------------------------------------------------------------- shape

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def req_str(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be a string")
    return v


def opt_str(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be a string")
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be an integer")
    if minimum is not None and v < minimum:
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be >= {minimum}")
    return v


def opt_int(data, field, default=None, minimum=None):
    v = data.get(field, default)
    if v is not None:
        if isinstance(v, bool) or not isinstance(v, int):
            raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer")
        if minimum is not None and v < minimum:
            raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be >= {minimum}")
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be a boolean")
    return v


def opt_bool(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be a boolean")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def opt_enum(data, field, allowed, default=None):
    v = data.get(field, default)
    if v is not None and (not isinstance(v, str) or v not in allowed):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def pdate(value):
    """Strict ISO calendar date (YYYY-MM-DD)."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def req_date(data, field):
    raw = data.get(field)
    d = pdate(raw)
    if d is None:
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be an ISO date (YYYY-MM-DD)")
    return raw  # keep the canonical string form for storage


def req_list(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, list):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be an array")
    return v


# ---------------------------------------------------------------- pagination

def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "Query parameter 'limit' must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "Query parameter 'offset' must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "Query parameter 'offset' must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (creation order), then apply limit/offset."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }


# ---------------------------------------------------------------- dates

def add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29 -> Feb 28
        return d.replace(year=d.year + years, day=28)


def add_days(d, days):
    return d + timedelta(days=days)


def occupied_dates(start_s, end_s):
    """Half-open [start_date, end_date) as a list of dates."""
    start = pdate(start_s)
    end = pdate(end_s)
    days = []
    d = start
    while d < end:
        days.append(d)
        d += timedelta(days=1)
    return days
