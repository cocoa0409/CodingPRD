"""Shared entity/system-field helpers and pagination."""
from decimal import Decimal, ROUND_HALF_UP
from flask import request
from db import db, new_id
from clock import clock
from errors import err


def stamp_new(entity):
    """Set system common fields on creation: id, created_at, updated_at, version."""
    now = clock.now_iso()
    entity.setdefault("id", new_id())
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def bump(entity):
    """Bump version + updated_at on mutation."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = clock.now_iso()
    return entity


def public(entity):
    """Strip private fields (leading underscore) for output."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def round_half_up(value):
    """Round a numeric value half-up to a whole integer."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- request body / query helpers ----

def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return v


def require_int(body, field, minimum=None):
    v = body.get(field)
    # bool is a subclass of int; reject it explicitly
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (field, minimum))
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def paginate(items):
    """Apply limit/offset query params (PRD §2.3). Returns (page, limit, offset, total)."""
    total = len(items)
    limit = _int_query("limit", default=10, minimum=1, maximum=100)
    offset = _int_query("offset", default=0, minimum=0, maximum=None)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def _int_query(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        v = int(raw)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "Query param %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Query param %s below minimum" % name)
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", "Query param %s above maximum" % name)
    return v


def sorted_by_creation(collection):
    """Ascending by creation (_seq mirrors created_at ordering deterministically)."""
    return sorted(collection, key=lambda e: e["_seq"])
