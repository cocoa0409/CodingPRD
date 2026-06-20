"""Shared helpers: date arithmetic, validation, entity scaffolding."""
from datetime import datetime, timedelta, timezone

from db import new_id, now_iso, db
from errors import err

ROLES = {"JurisdictionAdmin", "IntakeProcessor", "CaseInvestigator", "ContactTracer", "EpiAnalyst"}


# ---------------------------------------------------------------------------
# Date arithmetic — whole days against UTC-midnight datetimes
# ---------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ERR_INVALID_REQUEST on a malformed value.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Invalid datetime value")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def at_utc_midnight(dt):
    """Normalize a datetime to UTC midnight (date component only)."""
    if dt is None:
        return None
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def add_days(dt, days):
    if dt is None:
        return None
    return at_utc_midnight(dt) + timedelta(days=days)


def day_diff(a, b):
    """Absolute difference in whole days between two datetimes."""
    return abs((at_utc_midnight(a) - at_utc_midnight(b)).days)


# ---------------------------------------------------------------------------
# Common system fields
# ---------------------------------------------------------------------------
def base_entity(common_fields=True):
    ts = now_iso()
    ent = {
        "id": new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if common_fields:
        ent["updated_at"] = ts
        ent["version"] = 1
    return ent


def touch(ent):
    """Refresh updated_at and bump version on mutation."""
    ent["updated_at"] = now_iso()
    if "version" in ent:
        ent["version"] = ent["version"] + 1


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def require_fields(body, fields):
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be an object")
    for f in fields:
        if body.get(f) is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_non_negative_int(body, field, required=True):
    v = body.get(field)
    if v is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "%s must be a non-negative integer" % field)
    if v < 0:
        raise err("ERR_INVALID_REQUEST", "%s must be non-negative" % field)
    return v


def require_non_negative_number(body, field, required=True):
    v = body.get(field)
    if v is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "%s must be a non-negative number" % field)
    if v < 0:
        raise err("ERR_INVALID_REQUEST", "%s must be non-negative" % field)
    return v


def require_enum(body, field, allowed, required=True):
    v = body.get(field)
    if v is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", "%s must be one of %s" % (field, sorted(allowed)))
    return v


def require_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be a boolean" % field)
    return v


def require_string(body, field, required=True):
    v = body.get(field)
    if v is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a string" % field)
    return v


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination(args):
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def sorted_by_creation(items):
    return sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Existence lookups
# ---------------------------------------------------------------------------
def get_or_404(collection, _id, error_id):
    ent = collection.get(_id)
    if ent is None:
        raise err(error_id, "Resource not found")
    return ent


def get_in_program_or_404(collection, _id, program_id, error_id):
    """Resolve a body foreign key that must reference an existing row WITHIN the
    same program (PRD 2.5). A row that exists but belongs to a different program
    is treated as unresolved and surfaces the matching not-found error."""
    ent = collection.get(_id)
    if ent is None or ent.get("program_id") != program_id:
        raise err(error_id, "Resource not found in program")
    return ent
