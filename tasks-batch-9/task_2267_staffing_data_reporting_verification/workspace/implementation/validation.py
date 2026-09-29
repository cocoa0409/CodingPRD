"""Request body / query parsing and the typed field validators.

The helpers here map onto the pinned rejection order of PRD 2.11:

* ``fk_*`` helpers implement step 12 (body foreign keys resolve).  They are
  deliberately tolerant of an absent key so that a missing required field
  falls through to step 13 instead of producing a not-found.
* ``need_*`` helpers implement step 13 (required field present, declared type).
* ``check_enum`` implements step 14.
* ``parse_date`` / ``parse_time`` / ``parse_dt`` implement step 16.
"""

import re
from datetime import date, datetime, timezone
from decimal import Decimal

from flask import request

from errors import ApiError

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def bad(key, why="is missing or of the wrong type"):
    return ApiError("ERR_INVALID_REQUEST", message="Body field '%s' %s." % (key, why))


# --------------------------------------------------------------------------
# step 13 — required fields and declared types
# --------------------------------------------------------------------------

def has(b, key):
    return key in b and b[key] is not None


def need_str(b, key, allow_empty=False):
    v = b.get(key)
    if not isinstance(v, str):
        raise bad(key)
    if not allow_empty and v.strip() == "":
        raise bad(key, "must be a non-empty string")
    return v


def opt_str(b, key, default=None, allow_empty=False):
    if not has(b, key):
        return default
    return need_str(b, key, allow_empty=allow_empty)


def need_int(b, key):
    v = b.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad(key, "must be an integer")
    return v


def opt_int(b, key, default=None):
    if not has(b, key):
        return default
    return need_int(b, key)


def need_num(b, key):
    v = b.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise bad(key, "must be a number")
    return Decimal(str(v))


def need_bool(b, key):
    v = b.get(key)
    if not isinstance(v, bool):
        raise bad(key, "must be a boolean")
    return v


def opt_bool(b, key, default=None):
    if not has(b, key):
        return default
    return need_bool(b, key)


def need_list(b, key):
    v = b.get(key)
    if not isinstance(v, list):
        raise bad(key, "must be an array")
    return v


def need_int_min(b, key, minimum):
    v = need_int(b, key)
    if v < minimum:
        raise bad(key, "must be >= %d" % minimum)
    return v


# --------------------------------------------------------------------------
# step 14 — enums
# --------------------------------------------------------------------------

def check_enum(value, allowed, key):
    if value not in allowed:
        raise ApiError(
            "ERR_INVALID_ENUM_VALUE",
            message="Body field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))),
        )
    return value


# --------------------------------------------------------------------------
# step 16 — dates, times of day, datetimes
# --------------------------------------------------------------------------

def parse_date(value, key):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ApiError("ERR_INVALID_DATE_FORMAT", message="'%s' must be a YYYY-MM-DD date." % key)
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        raise ApiError("ERR_INVALID_DATE_FORMAT", message="'%s' is not a real calendar date." % key)


def parse_time(value, key):
    """Return minutes since midnight for an HH:MM 24-hour time of day."""
    if not isinstance(value, str) or not TIME_RE.match(value):
        raise ApiError("ERR_INVALID_DATE_FORMAT", message="'%s' must be an HH:MM time of day." % key)
    hh = int(value[0:2])
    mm = int(value[3:5])
    if hh > 23 or mm > 59:
        raise ApiError("ERR_INVALID_DATE_FORMAT", message="'%s' must be an HH:MM time of day." % key)
    return hh * 60 + mm


def parse_dt(value, key):
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_INVALID_DATE_FORMAT", message="'%s' must be an ISO 8601 UTC instant." % key)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError("ERR_INVALID_DATE_FORMAT", message="'%s' must be an ISO 8601 UTC instant." % key)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# step 12 — body foreign keys
# --------------------------------------------------------------------------

def fk(b, key, coll, error_id):
    """Resolve a body FK.

    Absent (or explicitly null) yields None so that step 13 can raise
    ERR_INVALID_REQUEST for a required field.  A value that is present but does
    not resolve raises the entity's own not-found code.
    """
    if not has(b, key):
        return None
    ident = b[key]
    if not isinstance(ident, str):
        raise ApiError(error_id)
    row = coll.get(ident)
    if row is None:
        raise ApiError(error_id)
    return row


def qfk(value, coll, error_id):
    """Resolve a query-string FK the same way."""
    if value is None:
        return None
    row = coll.get(value)
    if row is None:
        raise ApiError(error_id)
    return row


# --------------------------------------------------------------------------
# allocation lines — shared by hour capture, allocation replacement, batches
# --------------------------------------------------------------------------

def resolve_allocation_fks(value, categories):
    """Step 12 over an allocations array; tolerant of a malformed shape."""
    if not isinstance(value, list):
        return
    for line in value:
        if isinstance(line, dict):
            ident = line.get("job_category_id")
            if isinstance(ident, str) and ident not in categories:
                raise ApiError("ERR_JOB_CATEGORY_NOT_FOUND")
            if ident is not None and not isinstance(ident, str):
                raise ApiError("ERR_JOB_CATEGORY_NOT_FOUND")


def allocation_lines(value, key="allocations"):
    """Step 13 over an allocations array; returns normalised lines in order."""
    if not isinstance(value, list):
        raise bad(key, "must be an array")
    lines = []
    for index, line in enumerate(value):
        label = "%s[%d]" % (key, index)
        if not isinstance(line, dict):
            raise bad(label, "must be an object")
        ident = line.get("job_category_id")
        if not isinstance(ident, str) or not ident.strip():
            raise bad(label + ".job_category_id")
        percent = line.get("percent")
        if isinstance(percent, bool) or not isinstance(percent, (int, float)):
            raise bad(label + ".percent", "must be a number")
        lines.append({"job_category_id": ident, "percent": Decimal(str(percent))})
    return lines
