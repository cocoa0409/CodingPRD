"""Shared helpers: entity stamping, request payload validation, date math."""

import calendar
import uuid
from datetime import timedelta

import db
from db import _parse_iso, _format_iso, _format_iso_business
from errors import raise_error, ERR_VALIDATION


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def stamp_new(rec):
    """Stamp a freshly created entity with id/created_at/updated_at/version=1."""
    now = db.clock.now()
    rec["id"] = new_id()
    rec["created_at"] = _format_iso(now)
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and increment version on every mutation (PRD 2.4)."""
    rec["updated_at"] = _format_iso(db.clock.now())
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Date/time math (PRD 2.8 — both variants preserve time-of-day)
# ---------------------------------------------------------------------------

def parse_dt(value):
    return _parse_iso(value)


def fmt_business(dt):
    return _format_iso_business(dt)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # Feb 29 -> Feb 28
        return dt.replace(year=dt.year + years, day=28)


def add_months(dt, months):
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    day = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=day)


def calendar_roll_forward(basis, offset_days):
    """CALENDAR_ROLL_FORWARD: +calendar days, then roll past Saturday/Sunday (UTC)."""
    due = basis + timedelta(days=offset_days)
    while due.weekday() >= 5:  # 5 == Saturday, 6 == Sunday
        due += timedelta(days=1)
    return due


def business_day_count(basis, offset_days):
    """BUSINESS_DAY_COUNT: count Mon..Fri days, excluding the basis day itself."""
    due = basis
    counted = 0
    while counted < offset_days:
        due += timedelta(days=1)
        if due.weekday() < 5:
            counted += 1
    return due


# ---------------------------------------------------------------------------
# Request payload helpers (schema validation -> ERR_VALIDATION 400)
# ---------------------------------------------------------------------------

def get_payload():
    from flask import request
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def reject_unknown_fields(body, allowed):
    for key in body:
        if key not in allowed:
            raise_error(ERR_VALIDATION, "Unknown field: %s" % key)


def require_field(body, name):
    if name not in body or body[name] is None:
        raise_error(ERR_VALIDATION, "Missing required field: %s" % name)
    return body[name]


def require_string(body, name):
    v = require_field(body, name)
    if not isinstance(v, str):
        raise_error(ERR_VALIDATION, "Field %s must be a string" % name)
    return v


def optional_string(body, name, default=None):
    v = body.get(name, default)
    if v is not None and not isinstance(v, str):
        raise_error(ERR_VALIDATION, "Field %s must be a string" % name)
    return v


def require_int(body, name, minimum=None, maximum=None):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_VALIDATION, "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise_error(ERR_VALIDATION, "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        raise_error(ERR_VALIDATION, "Field %s must be <= %s" % (name, maximum))
    return v


def optional_int(body, name, default=None, minimum=None, maximum=None):
    v = body.get(name, default)
    if v is None:
        return v
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_VALIDATION, "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise_error(ERR_VALIDATION, "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        raise_error(ERR_VALIDATION, "Field %s must be <= %s" % (name, maximum))
    return v


def require_number(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_VALIDATION, "Field %s must be a number" % name)
    return v


def require_bool(body, name):
    v = require_field(body, name)
    if not isinstance(v, bool):
        raise_error(ERR_VALIDATION, "Field %s must be a boolean" % name)
    return v


def require_array(body, name):
    v = require_field(body, name)
    if not isinstance(v, list):
        raise_error(ERR_VALIDATION, "Field %s must be an array" % name)
    return v


def optional_array(body, name, default=None):
    v = body.get(name, default)
    if v is not None and not isinstance(v, list):
        raise_error(ERR_VALIDATION, "Field %s must be an array" % name)
    return v


def require_enum(body, name, allowed):
    v = require_field(body, name)
    if not isinstance(v, str) or v not in allowed:
        raise_error(ERR_VALIDATION, "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def require_datetime(body, name):
    v = require_field(body, name)
    if not isinstance(v, str):
        raise_error(ERR_VALIDATION, "Field %s must be an ISO 8601 string" % name)
    try:
        return _parse_iso(v)
    except (ValueError, TypeError):
        raise_error(ERR_VALIDATION, "Field %s must be a valid ISO 8601 timestamp" % name)


def optional_datetime(body, name, default=None):
    v = body.get(name, default)
    if v is None:
        return v
    if not isinstance(v, str):
        raise_error(ERR_VALIDATION, "Field %s must be an ISO 8601 string" % name)
    try:
        return _parse_iso(v)
    except (ValueError, TypeError):
        raise_error(ERR_VALIDATION, "Field %s must be a valid ISO 8601 timestamp" % name)


def require_nice_classes(body, name, require_nonempty):
    v = require_array(body, name)
    if require_nonempty and len(v) == 0:
        raise_error(ERR_VALIDATION, "Field %s requires at least one entry" % name)
    for item in v:
        if isinstance(item, bool) or not isinstance(item, int) or item < 1 or item > 45:
            raise_error(ERR_VALIDATION, "Field %s entries must be Nice class integers 1..45" % name)
    return v


def require_class_array(body, name):
    """conflicting_classes: array of Nice class integers."""
    v = require_array(body, name)
    for item in v:
        if isinstance(item, bool) or not isinstance(item, int):
            raise_error(ERR_VALIDATION, "Field %s entries must be integers" % name)
    return v


def coerce_version(body, name):
    """OCC expected_*_version field: integer (a digit string is tolerated)."""
    v = require_field(body, name)
    if isinstance(v, bool):
        raise_error(ERR_VALIDATION, "Field %s must be an integer" % name)
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.lstrip("-").isdigit():
        return int(v)
    raise_error(ERR_VALIDATION, "Field %s must be an integer" % name)
