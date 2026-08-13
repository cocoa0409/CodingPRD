"""Shared helpers: request-body validation, date handling, pagination,
and the versioning contract of PRD §2.4."""

from datetime import datetime, timezone, timedelta
from flask import request
import errors
from db import new_id, now_iso


# ---------------------------------------------------------------------------
# Date / time handling
# ---------------------------------------------------------------------------

def parse_datetime(value, field):
    """Parse an ISO 8601 timestamp. Raises ERR_INVALID_REQUEST on failure."""
    if not isinstance(value, str):
        raise errors.invalid_request("Field '%s' must be an ISO8601 string" % field)
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise errors.invalid_request("Field '%s' is not a parseable ISO8601 date" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    """Parse a date-granularity field pinned to UTC midnight (PRD §2.5)."""
    dt = parse_datetime(value, field)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def iso_z(dt):
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def day_count(start_date, end_date):
    """Whole-day count of the half-open window [start, end), minimum 1."""
    days = int((end_date - start_date).total_seconds() // 86400)
    return max(1, days)


# ---------------------------------------------------------------------------
# Request body validation helpers (gate 16 — checked last at call site)
# ---------------------------------------------------------------------------

def body():
    """Return the JSON request body, tolerating missing bodies on POST actions."""
    if request.is_json:
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise errors.invalid_request("Request body must be a JSON object")
        return data
    return {}


def req_str(data, field):
    v = data.get(field)
    if v is None:
        raise errors.invalid_request("Missing required field: %s" % field)
    if not isinstance(v, str) or v == "":
        raise errors.invalid_request("Field '%s' must be a non-empty string" % field)
    return v


def opt_str(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, str):
        raise errors.invalid_request("Field '%s' must be a string" % field)
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if v is None:
        raise errors.invalid_request("Missing required field: %s" % field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request("Field '%s' must be an integer" % field)
    if minimum is not None and v < minimum:
        raise errors.invalid_request("Field '%s' must be >= %d" % (field, minimum))
    return v


def opt_int(data, field, default=None, minimum=None):
    v = data.get(field, default)
    if v is not None:
        if isinstance(v, bool) or not isinstance(v, int):
            raise errors.invalid_request("Field '%s' must be an integer" % field)
        if minimum is not None and v < minimum:
            raise errors.invalid_request("Field '%s' must be >= %d" % (field, minimum))
    return v


def opt_bool(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, bool):
        raise errors.invalid_request("Field '%s' must be a boolean" % field)
    return v


def req_enum(data, field, allowed):
    v = req_str(data, field)
    if v not in allowed:
        raise errors.invalid_request("Field '%s' must be one of %s" % (field, sorted(allowed)))
    return v


def opt_enum(data, field, allowed, default=None):
    v = data.get(field, default)
    if v is not None:
        if not isinstance(v, str) or v not in allowed:
            raise errors.invalid_request("Field '%s' must be one of %s" % (field, sorted(allowed)))
    return v


def opt_str_list(data, field, default=None):
    v = data.get(field, default)
    if v is not None:
        if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
            raise errors.invalid_request("Field '%s' must be an array of strings" % field)
    return v


def req_str_list(data, field):
    v = data.get(field)
    if v is None:
        raise errors.invalid_request("Missing required field: %s" % field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise errors.invalid_request("Field '%s' must be an array of strings" % field)
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def pagination_params():
    """Read limit/offset query params with defaults, min and max."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.invalid_request("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("Query parameter 'limit' must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.invalid_request("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise errors.invalid_request("Query parameter 'offset' must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Slice a created_at-ascending list and build the pagination meta block."""
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}


# ---------------------------------------------------------------------------
# Resource lifecycle (PRD §2.4 versioning contract)
# ---------------------------------------------------------------------------

def new_resource():
    """System-managed fields stamped on every resource at creation."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(resource):
    """Refresh updated_at and increment version on every mutation of a
    resource — including cascaded resources the client did not name (§2.4)."""
    resource["updated_at"] = now_iso()
    resource["version"] = resource.get("version", 1) + 1


def sort_by_created(items):
    """Default list ordering: creation timestamp ascending (PRD §2.3)."""
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))
