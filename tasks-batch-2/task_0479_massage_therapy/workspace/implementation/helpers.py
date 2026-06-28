"""Entity scaffolding, request parsing, pagination, validation helpers."""
from flask import request

import clock
import db
import util
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND


# ---------------------------------------------------------------------------
# System-managed common fields (PRD §2.4)
# ---------------------------------------------------------------------------

def new_entity(fields, versioned=True):
    """Create an entity dict with id/created_at(/updated_at/version)."""
    now = util.now_iso()
    base = {
        "id": util.new_uuid(),
        "created_at": now,
    }
    if versioned:
        base["updated_at"] = now
        base["version"] = 1
    base.update(fields)
    # internal seq for stable sort
    base["_seq"] = db.next_seq()
    return base


def touch(entity):
    """Bump version and refresh updated_at on a successful mutation (PRD §2.4)."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = util.now_iso()


def public(entity):
    """Strip internal fields before serialization."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Request body parsing
# ---------------------------------------------------------------------------

def get_body():
    if request.content_length in (None, 0) and not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(*ERR_INVALID_REQUEST, message="Body must be an object")
    return data


def require(body, key):
    if key not in body or body[key] is None:
        raise ApiError(*ERR_INVALID_REQUEST, message=f"Missing required field: {key}")
    return body[key]


def opt(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    return body[key]


def as_int(value, key, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(*ERR_INVALID_REQUEST, message=f"{key} must be an integer")
    if minimum is not None and value < minimum:
        raise ApiError(*ERR_INVALID_REQUEST, message=f"{key} below minimum")
    if maximum is not None and value > maximum:
        raise ApiError(*ERR_INVALID_REQUEST, message=f"{key} above maximum")
    return value


def as_str(value, key):
    if not isinstance(value, str):
        raise ApiError(*ERR_INVALID_REQUEST, message=f"{key} must be a string")
    return value


def as_bool(value, key):
    if not isinstance(value, bool):
        raise ApiError(*ERR_INVALID_REQUEST, message=f"{key} must be a boolean")
    return value


def as_fraction_pct(value, key):
    """A fraction between 0 and 1 inclusive."""
    from numbers import Number
    if isinstance(value, bool) or not isinstance(value, Number):
        raise ApiError(*ERR_INVALID_REQUEST, message=f"{key} must be a number")
    from fractions import Fraction
    f = Fraction(str(value)) if isinstance(value, float) else Fraction(value)
    if f < 0 or f > 1:
        raise ApiError(*ERR_INVALID_REQUEST, message=f"{key} must be between 0 and 1")
    return f


def enum(value, key, choices):
    if value not in choices:
        raise ApiError(*ERR_INVALID_REQUEST, message=f"{key} must be one of {choices}")
    return value


# ---------------------------------------------------------------------------
# Existence resolution (PRD §2.9)
# ---------------------------------------------------------------------------

def resolve(store, entity_id):
    ent = store.get(entity_id)
    if ent is None:
        raise ApiError(*ERR_NOT_FOUND, message="Resource not found")
    return ent


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def get_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError(*ERR_INVALID_REQUEST, message="limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(*ERR_INVALID_REQUEST, message="limit out of range")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError(*ERR_INVALID_REQUEST, message="offset must be an integer")
        if offset < 0:
            raise ApiError(*ERR_INVALID_REQUEST, message="offset must be non-negative")
    return limit, offset


def get_bool_flag(name, default=False):
    raw = request.args.get(name)
    if raw is None:
        return default
    return raw.lower() in ("true", "1", "yes")


def paginate(items, limit, offset):
    """Sort by created_at asc (then by seq), window, return (page, total)."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
