"""Per-request helpers: body parsing, existence resolution, pagination,
field/type validation.
"""
from flask import request

from errors import err


def get_json_body():
    """Return the parsed JSON object body, or {} when absent.

    A body present but not a JSON object raises ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "body must be a JSON object")
    return data


def require_resource(collection, rid, label="resource"):
    """Resolve an id against a collection or raise ERR_NOT_FOUND."""
    if rid is None:
        raise err("ERR_NOT_FOUND", "%s not found" % label)
    rec = collection.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "%s not found" % label)
    return rec


def require_fields(body, fields):
    """Ensure each named field is present and non-null; else ERR_INVALID_REQUEST."""
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "missing field: %s" % f)


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v.strip() == "":
        raise err("ERR_INVALID_REQUEST", "%s must be a non-empty string" % field)
    return v


def require_int(body, field):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    return v


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be a boolean" % field)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "%s must be one of %s" % (field, sorted(allowed)))
    return v


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    return require_enum(body, field, allowed)


def require_fault_pct(body, field, default=0):
    """fault percentage integer 0..100 inclusive."""
    if field not in body or body[field] is None:
        v = default
    else:
        v = body[field]
        if not isinstance(v, int) or isinstance(v, bool):
            raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if v < 0 or v > 100:
        raise err("ERR_INVALID_REQUEST", "%s must be within 0..100" % field)
    return v


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3.

    limit defaults 10, min 1, max 100. offset defaults 0, min 0.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range [1,100]")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (stable via _seq) and slice the page."""
    ordered = sorted(records, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
