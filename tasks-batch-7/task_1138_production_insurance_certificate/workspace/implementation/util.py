"""Shared helpers: datetime handling, validation, serialization, pagination."""

from datetime import datetime, timedelta, timezone

from flask import request

from db import db, new_id
from errors import err


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------

def parse_dt(value, field):
    """Parse an ISO8601 datetime. Accepts trailing Z or numeric offset."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an ISO8601 datetime string" % field)
    text = value.strip()
    if not text:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty ISO8601 datetime" % field)
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Field '%s' is not a valid ISO8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
    s += "%03dZ" % (dt.microsecond // 1000)
    return s


def now():
    """Current logical time."""
    return db.current_utc


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_months(dt, months):
    """Calendar-month addition with day clamping."""
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    if m == 2:
        leap = (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0)
        dmax = 29 if leap else 28
    elif m in (4, 6, 9, 11):
        dmax = 30
    else:
        dmax = 31
    return dt.replace(year=y, month=m, day=min(dt.day, dmax))


# ---------------------------------------------------------------------------
# Field validation helpers
# ---------------------------------------------------------------------------

def body():
    """JSON request body as a dict; missing/malformed body reads as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def req_string(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required and must be a non-empty string" % field)
    return v


def opt_string(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a string" % field)
    return v


def req_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required and must be an integer" % field)
    return v


def opt_bool(data, field, default):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a boolean" % field)
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required and must be a string" % field)
    if v not in allowed:
        raise err("ERR_INVALID_ENUM", "Field '%s' must be one of %s" % (field, sorted(allowed)))
    return v


def req_dt(data, field):
    return parse_dt(data.get(field), field)


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

def make_entity(extra_fields):
    """Create a base entity record with common system fields."""
    ts = now()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(extra_fields)
    return rec


def touch(rec):
    """Register a mutation: bump version and refresh updated_at."""
    rec["version"] += 1
    rec["updated_at"] = now()


# ---------------------------------------------------------------------------
# Serialization (strips internal fields, converts datetimes)
# ---------------------------------------------------------------------------

def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def pagination_params():
    """Parse limit/offset query params with scaffold defaults.

    limit: default 10, min 1, max 100 (clamped); offset: default 0 (clamped).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(records):
    """Sort by created_at ascending and apply limit/offset."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=sort_key)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(r) for r in page], {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


# ---------------------------------------------------------------------------
# Lookup helpers (404 on miss)
# ---------------------------------------------------------------------------

def get_or_404(collection, entity_id, label):
    rec = collection.get(entity_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "%s '%s' not found" % (label, entity_id))
    return rec


def get_production(prod_id):
    return get_or_404(db.productions, prod_id, "Production")


def get_child(collection, child_id, parent_field, parent_id, label):
    """Resolve a nested child, verifying it belongs to the parent in the path."""
    rec = collection.get(child_id)
    if rec is None or rec.get(parent_field) != parent_id:
        raise err("ERR_NOT_FOUND", "%s '%s' not found" % (label, child_id))
    return rec
