"""Shared helpers: ids, timestamps, payload validation, pagination, dates."""

import uuid
from datetime import datetime, timedelta, timezone

from flask import request

import errors as E


# ---------------------------------------------------------------------------
# ids / timestamps
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def iso_z(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value, field=None):
    """Parse an ISO-8601 instant into an aware UTC datetime; ERR_VALIDATION on failure."""
    try:
        if not isinstance(value, str):
            raise ValueError
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        E.raise_err(E.ERR_VALIDATION, f"Field '{field or 'timestamp'}' must be an ISO-8601 instant")


def parse_date(value, field=None):
    """Parse a YYYY-MM-DD calendar date; ERR_VALIDATION on failure."""
    try:
        if not isinstance(value, str):
            raise ValueError
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        E.raise_err(E.ERR_VALIDATION, f"Field '{field or 'date'}' must be a YYYY-MM-DD date")


def touch(entity):
    """Refresh updated_at and bump version by exactly 1 (PRD §2.4)."""
    entity["updated_at"] = iso_z(now_logical())
    entity["version"] = entity["version"] + 1


def now_logical():
    from db import store
    return store.now()


def stamp_new(entity):
    ts = iso_z(now_logical())
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


# ---------------------------------------------------------------------------
# payload validation
# ---------------------------------------------------------------------------

def body():
    """Return the JSON request body as a dict; empty body -> {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        E.raise_err(E.ERR_VALIDATION, "Request body must be a JSON object")
    return data


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        E.raise_err(E.ERR_VALIDATION, f"Missing or invalid required field: {field}")
    return v


def opt_str(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        E.raise_err(E.ERR_VALIDATION, f"Field '{field}' must be a string")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        E.raise_err(E.ERR_VALIDATION, f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def opt_enum(data, field, allowed, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        E.raise_err(E.ERR_VALIDATION, f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def req_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        E.raise_err(E.ERR_VALIDATION, f"Field '{field}' must be an integer")
    return v


def opt_int(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        E.raise_err(E.ERR_VALIDATION, f"Field '{field}' must be an integer")
    return v


def req_number(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        E.raise_err(E.ERR_VALIDATION, f"Field '{field}' must be a number")
    return float(v)


def opt_number(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        E.raise_err(E.ERR_VALIDATION, f"Field '{field}' must be a number")
    return float(v)


def opt_bool(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        E.raise_err(E.ERR_VALIDATION, f"Field '{field}' must be a boolean")
    return v


def req_str_list(data, field, allowed=None):
    v = data.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        E.raise_err(E.ERR_VALIDATION, f"Field '{field}' must be an array of strings")
    if allowed is not None:
        for x in v:
            if x not in allowed:
                E.raise_err(E.ERR_VALIDATION, f"Field '{field}' contains an invalid member: {x}")
    return list(v)


def opt_str_list(data, field, allowed=None, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        E.raise_err(E.ERR_VALIDATION, f"Field '{field}' must be an array of strings")
    if allowed is not None:
        for x in v:
            if x not in allowed:
                E.raise_err(E.ERR_VALIDATION, f"Field '{field}' contains an invalid member: {x}")
    return list(v)


# ---------------------------------------------------------------------------
# pagination (PRD §2.3: limit default 10 min 1 max 100, offset default 0)
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            E.raise_err(E.ERR_VALIDATION, "Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            E.raise_err(E.ERR_VALIDATION, "Query parameter 'limit' must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            E.raise_err(E.ERR_VALIDATION, "Query parameter 'offset' must be an integer")
        if offset < 0:
            E.raise_err(E.ERR_VALIDATION, "Query parameter 'offset' must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Items must already be sorted by created_at ascending (ties by id for
    determinism)."""
    total = len(items)
    return items[offset:offset + limit], total


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))


# ---------------------------------------------------------------------------
# OCC helper (PRD §2.7)
# ---------------------------------------------------------------------------

def check_occ(data, field, current_version):
    supplied = data.get(field)
    if supplied is None:
        E.raise_err(E.ERR_VALIDATION, f"Missing required field: {field}")
    if isinstance(supplied, bool) or not isinstance(supplied, int):
        E.raise_err(E.ERR_VALIDATION, f"Field '{field}' must be an integer")
    if supplied != current_version:
        E.raise_err(E.ERR_STALE_VERSION, f"{field} does not match current version")


# ---------------------------------------------------------------------------
# after-hours window (PRD §2.5): [22:00, 07:00) UTC time-of-day
# ---------------------------------------------------------------------------

def is_after_hours_instant(dt):
    """True when the UTC wall-clock time-of-day of dt is in [22:00, 07:00)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.hour >= 22 or dt.hour < 7


def shift_intersects_after_hours(starts_at, ends_at):
    """True when the half-open window [starts_at, ends_at) intersects the
    22:00-07:00 UTC after-hours window on any covered day."""
    if ends_at <= starts_at:
        return False
    # Check each calendar day touched by the window, plus the boundary day.
    day = starts_at.astimezone(timezone.utc).date()
    last_day = (ends_at - timedelta(microseconds=1)).astimezone(timezone.utc).date()
    one = timedelta(days=1)
    while day <= last_day:
        ah_start = datetime(day.year, day.month, day.day, 22, 0, tzinfo=timezone.utc)
        ah_end = ah_start + timedelta(hours=9)  # next day 07:00
        if starts_at < ah_end and ah_start < ends_at:
            return True
        # Also the early-morning portion 00:00-07:00 of this day.
        early_start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=timezone.utc)
        early_end = early_start + timedelta(hours=7)
        if starts_at < early_end and early_start < ends_at:
            return True
        day = day + one
    return False
