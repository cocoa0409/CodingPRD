"""Shared helpers: entity CRUD plumbing, validation, pagination, timestamps."""

from datetime import datetime, timezone, timedelta

from flask import request

from db import DB, new_id, now_iso
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import success_list


# ---------------------------------------------------------------------------
# Entity construction / mutation
# ---------------------------------------------------------------------------

def make_entity(fields):
    ts = now_iso()
    ent = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
    ent.update(fields)
    return ent


def touch(ent):
    """Refresh updated_at and bump version on a mutation."""
    ent["updated_at"] = now_iso()
    ent["version"] = ent.get("version", 1) + 1


def touch_no_version(ent):
    ent["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def lookup(table, entity_id, label="resource"):
    ent = table.get(entity_id)
    if ent is None:
        raise ApiError(ERR_NOT_FOUND, f"{label} {entity_id} not found", 404)
    return ent


# ---------------------------------------------------------------------------
# Body parsing / field validation
# ---------------------------------------------------------------------------

def body():
    if not request.is_json:
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be JSON", 400)
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {name}", 400)
    return data[name]


def opt_field(data, name, default=None):
    v = data.get(name, default)
    return default if v is None else v


def req_string(data, name):
    v = req_field(data, name)
    if not isinstance(v, str) or not v:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string", 400)
    return v


def req_int(data, name, min_value=None, allow_zero=False):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be an integer", 400)
    if min_value is not None and v < min_value:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be >= {min_value}", 400)
    if not allow_zero and min_value is None and v <= 0:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be > 0", 400)
    return v


def req_number(data, name, min_value=None, allow_zero=False):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be a number", 400)
    if min_value is not None and v < min_value:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be >= {min_value}", 400)
    if not allow_zero and min_value is None and v <= 0:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be > 0", 400)
    return v


def req_enum(data, name, allowed):
    v = req_field(data, name)
    if v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Field {name} must be one of {sorted(allowed)}",
            400,
        )
    return v


def opt_enum(data, name, allowed, default):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Field {name} must be one of {sorted(allowed)}",
            400,
        )
    return v


def parse_iso_datetime(v, field_name="datetime"):
    """Parse an ISO 8601 datetime with timezone. Returns aware datetime."""
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field_name} must be a string", 400)
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field_name} is not a valid ISO 8601 datetime", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(v, field_name="date"):
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field_name} must be a string", 400)
    try:
        d = datetime.strptime(v.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field_name} must be YYYY-MM-DD", 400)
    return d


def parse_period(v, field_name="period"):
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field_name} must be a string", 400)
    try:
        datetime.strptime(v.strip(), "%Y-%m")
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field_name} must be YYYY-MM", 400)
    return v.strip()


def iso_z(dt):
    """Render aware datetime as ISO 8601 UTC, second precision, trailing Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(items, filters=None):
    """Sort by created_at ascending, apply equality filters, paginate."""
    filtered = list(items)
    if filters:
        for key, val in filters.items():
            if val is not None:
                filtered = [e for e in filtered if str(e.get(key)) == str(val)]
    filtered.sort(key=lambda e: (e.get("created_at", ""), e.get("id", "")))
    total = len(filtered)
    limit, offset = parse_pagination()
    page = filtered[offset:offset + limit]
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def public(ent):
    """Return a copy of the entity dict for serialization."""
    return dict(ent)
