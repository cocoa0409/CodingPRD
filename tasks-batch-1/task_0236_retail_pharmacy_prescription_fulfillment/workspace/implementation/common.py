"""Shared helpers: body parsing, validation primitives, system fields, paging."""
from flask import request

import db
from clock import now_iso
from errors import err

# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------


def get_body():
    """Return the parsed JSON body as a dict (empty dict when none).

    A body that is present but not a JSON object -> ERR_INVALID_REQUEST.
    """
    if request.content_length in (None, 0) and not (request.data or b"").strip():
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Typed field extraction (all raise ERR_INVALID_REQUEST on violation)
# ---------------------------------------------------------------------------


def require_field(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    return body[name]


def opt_field(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return body[name]


def as_string(value, name):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % name)
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % name)
    return value


def as_int(value, name, minimum=None, maximum=None):
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s" % (name, maximum))
    return value


def as_number(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % name)
    v = float(value)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s" % (name, maximum))
    return v


def as_enum(value, name, allowed):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (name, sorted(allowed)))
    return value


def as_string_array(value, name):
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an array of strings" % name)
    return value


# ---------------------------------------------------------------------------
# System fields (PRD §2.4 / §2.6)
# ---------------------------------------------------------------------------


def stamp_create(entity, versioned=True):
    """Set id/created_at (and updated_at/version for mutable resources)."""
    ts = now_iso()
    entity["id"] = db.new_id()
    entity["created_at"] = ts
    if versioned:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version on any mutation (PRD §2.6)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------


def get_pagination():
    """Read limit/offset query params (default 10 / 0, min 1, max 100)."""
    limit = _read_int_param("limit", 10, 1, 100)
    offset = _read_int_param("offset", 0, 0, None)
    return limit, offset


def _read_int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "Query param %s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", "Query param %s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", "Query param %s must be <= %s" % (name, maximum))
    return value


def paginate(items, limit, offset):
    """Sort by created_at ASC (PRD §2.3) and slice; returns (page, total)."""
    ordered = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
