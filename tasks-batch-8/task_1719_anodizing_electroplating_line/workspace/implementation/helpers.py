"""Shared helpers: common fields, pagination, schema validation."""
import math
from datetime import datetime, timezone

from flask import request

from db import new_id, now_iso
from errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND, raise_err


# ---------------------------------------------------------------------------
# Common fields
# ---------------------------------------------------------------------------

def stamp_new(entity):
    """Attach id/created_at/updated_at/version to a new primary resource."""
    entity["id"] = new_id()
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def stamp_event(entity):
    """Attach id/created_at to a new append-only event (no updated_at/version)."""
    entity["id"] = new_id()
    entity["created_at"] = now_iso()
    return entity


def touch(entity):
    """Refresh updated_at and bump version on a mutated primary resource."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
    return entity


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def parse_pagination():
    """Parse limit/offset query params. Defaults 10/0, min 1, max 100."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items already sorted by created_at ascending."""
    total = len(items)
    return items[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Schema validation utilities (tier 5)
# ---------------------------------------------------------------------------

def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise_err(ERR_INVALID_REQUEST, "missing required field: %s" % f)


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def check_string(data, field, required=True):
    v = data.get(field)
    if v is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, "missing required field: %s" % field)
        return None
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "%s must be a string" % field)
    return v


def check_enum(data, field, allowed, required=True, default=None):
    v = data.get(field)
    if v is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, "missing required field: %s" % field)
        return default
    if v not in allowed:
        raise_err(ERR_INVALID_REQUEST, "%s must be one of %s" % (field, sorted(allowed)))
    return v


def check_number(data, field, required=True, gt=None, gte=None, default=None):
    v = data.get(field)
    if v is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, "missing required field: %s" % field)
        return default
    if not is_number(v):
        raise_err(ERR_INVALID_REQUEST, "%s must be a number" % field)
    if gt is not None and not (v > gt):
        raise_err(ERR_INVALID_REQUEST, "%s must be > %s" % (field, gt))
    if gte is not None and not (v >= gte):
        raise_err(ERR_INVALID_REQUEST, "%s must be >= %s" % (field, gte))
    return v


def check_integer(data, field, required=True, gte=None, gt=None, default=None):
    v = data.get(field)
    if v is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, "missing required field: %s" % field)
        return default
    if not is_int(v):
        raise_err(ERR_INVALID_REQUEST, "%s must be an integer" % field)
    if gte is not None and not (v >= gte):
        raise_err(ERR_INVALID_REQUEST, "%s must be >= %s" % (field, gte))
    if gt is not None and not (v > gt):
        raise_err(ERR_INVALID_REQUEST, "%s must be > %s" % (field, gt))
    return v


def check_boolean(data, field, required=False, default=None):
    v = data.get(field)
    if v is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, "missing required field: %s" % field)
        return default
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, "%s must be a boolean" % field)
    return v


def check_array(data, field, required=True, min_len=None):
    v = data.get(field)
    if v is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, "missing required field: %s" % field)
        return None
    if not isinstance(v, list):
        raise_err(ERR_INVALID_REQUEST, "%s must be an array" % field)
    if min_len is not None and len(v) < min_len:
        raise_err(ERR_INVALID_REQUEST, "%s must have at least %d entries" % (field, min_len))
    return v


# ---------------------------------------------------------------------------
# Datetime parsing (logical-clock timestamps, permit window dates)
# ---------------------------------------------------------------------------

def parse_iso8601(value, field="timestamp"):
    """Parse an ISO8601 timestamp string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, "%s must be an ISO8601 string" % field)
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "%s is not a valid ISO8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field="date"):
    """Parse a YYYY-MM-DD date string to a date object."""
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, "%s must be a YYYY-MM-DD string" % field)
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "%s must be a YYYY-MM-DD date" % field)


# ---------------------------------------------------------------------------
# Existence helpers (tier 4)
# ---------------------------------------------------------------------------

def get_or_404(table, entity_id):
    entity = table.get(entity_id)
    if entity is None:
        raise_err(ERR_NOT_FOUND, "resource not found: %s" % entity_id)
    return entity
