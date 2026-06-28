"""Shared request parsing, datetime handling, pagination, and mutation helpers."""
from datetime import datetime, timezone

from flask import request

import errors
from db import db, iso_ms


# ----------------------------------------------------------------------------
# Body parsing
# ----------------------------------------------------------------------------
def get_body():
    if request.data and len(request.data) > 0:
        body = request.get_json(force=True, silent=True)
    else:
        body = {}
    if body is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return body[name]


def require_str(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or v == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return v


def require_int(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return v


def optional_int(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return v


def require_number(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a number")
    return v


def optional_number(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a number")
    return v


def optional_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return v


def require_bool(body, name):
    v = require_field(body, name)
    if not isinstance(v, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return v


def require_enum(body, name, allowed):
    v = require_field(body, name)
    if not isinstance(v, str) or v not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return v


# ----------------------------------------------------------------------------
# Datetime parsing (ISO 8601 UTC)
# ----------------------------------------------------------------------------
def parse_dt(value, field_name):
    if not isinstance(value, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field_name} must be an ISO 8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field_name} must be a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_dt(body, name):
    return parse_dt(require_field(body, name), name)


# ----------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, min 1, max 100; offset default 0.
# Out-of-bounds pagination parameters are malformed (ERR_INVALID_REQUEST).
# ----------------------------------------------------------------------------
def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit out of bounds (1..100)")
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset out of bounds (>= 0)")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (PRD 2.3), tie-break by creation sequence."""
    ordered = sorted(items, key=lambda x: (x.get("created_at", ""), x.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ----------------------------------------------------------------------------
# Existence lookups (raise ERR_NOT_FOUND)
# ----------------------------------------------------------------------------
def get_or_404(table, _id):
    obj = table.get(_id)
    if obj is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Referenced resource does not exist")
    return obj


# ----------------------------------------------------------------------------
# Mutation: bump updated_at + version
# ----------------------------------------------------------------------------
def touch(entity):
    entity["updated_at"] = iso_ms_now()
    entity["version"] += 1


def iso_ms_now():
    from clock import clock
    return iso_ms(clock.now())


def stamp_common(entity, versioned=True):
    ts = iso_ms_now()
    entity["created_at"] = ts
    entity["_seq"] = db.next_seq()
    if versioned:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity
