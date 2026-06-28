"""Shared helpers: common fields, mutation bookkeeping, pagination, input parsing.

Common resource properties (PRD Section 2.4): every resource carries id,
created_at, updated_at (refreshed on each mutation), and integer version
(starts at its initial value on create and increments by one on every mutation,
including cascade mutations per Section 2.5).
"""
from db import store
from errors import err


def new_entity(extra_fields):
    """Mint a new entity row with the common system fields + extra fields.

    version begins at 1 on create. _seq is a hidden monotonic insertion counter
    used purely for stable created_at-ASC ordering of ties.
    """
    now = store.now_iso()
    base = {
        "id": store.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    base.update(extra_fields)
    return base


def touch(entity):
    """Refresh updated_at and bump version on any mutation (direct or cascade)."""
    entity["updated_at"] = store.now_iso()
    entity["version"] = entity["version"] + 1


def public(entity):
    """Strip private bookkeeping fields (those prefixed with '_') for output."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# --- input parsing helpers ----------------------------------------------------

def get_json(req):
    """Return the request JSON body as a dict, or {} when absent/empty."""
    if not req.data:
        return {}
    try:
        body = req.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "%s is required" % field)
    return val


def optional_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a string" % field)
    return val


def require_enum(body, field, allowed):
    val = require_str(body, field)
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", "%s must be one of %s" % (field, sorted(allowed)))
    return val


def require_int(body, field, minimum=None):
    val = body.get(field)
    if not isinstance(val, int) or isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "%s must be >= %d" % (field, minimum))
    return val


def optional_int(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum=minimum)


def optional_number(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "%s must be a number" % field)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "%s must be >= %s" % (field, minimum))
    return val


# --- pagination (PRD Section 2.3) ---------------------------------------------
# limit defaults to 10, min 1, max 100. offset defaults to 0, min 0.
# Out-of-range -> ERR_VALIDATION (422).

def parse_pagination(args):
    limit = _parse_pagination_int(args, "limit", 10)
    offset = _parse_pagination_int(args, "offset", 0)
    if limit < 1 or limit > 100:
        raise err("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset < 0:
        raise err("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def _parse_pagination_int(args, name, default):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", "%s must be an integer" % name)


def paginate(rows, limit, offset):
    """Sort by created_at ASC (stable via _seq), slice, and build meta.

    Returns (page_rows, pagination_meta). Sorting is by the hidden insertion
    sequence which is monotone in created_at (PRD Section 2.3: list endpoints
    return resources sorted by creation timestamp ascending).
    """
    ordered = sorted(rows, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
