"""Shared route helpers: body validation, pagination, common-field stamping."""
from flask import request

from errors import raise_error, ERR_VALIDATION, ERR_NOT_FOUND
from util import new_id, now_ts


# ---------------------------------------------------------------------------
# Body validation (priority 0: ERR_VALIDATION before auth per PRD 2.6 —
# "A structurally malformed body ... fails first with ERR_VALIDATION").
# PRD 2.6 ordering puts malformed-body first. However auth headers are checked
# even before body parsing in many suites; PRD explicitly says malformed body
# fails first, so routes call body validation BEFORE get_caller().
# ---------------------------------------------------------------------------

def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION, "request body must be a JSON object")
    return body


def req_field(body, name, types, allow_null=False):
    """Require a field of one of the given python types."""
    if name not in body:
        raise_error(ERR_VALIDATION, f"missing required field: {name}")
    val = body[name]
    if val is None and allow_null:
        return val
    if not isinstance(val, types) or (isinstance(val, bool) and bool not in (types if isinstance(types, tuple) else (types,))):
        raise_error(ERR_VALIDATION, f"field {name} has wrong type")
    return val


def opt_field(body, name, types, default=None, allow_null=False):
    if name not in body:
        return default
    val = body[name]
    if val is None:
        if allow_null:
            return val
        return default
    if not isinstance(val, types) or isinstance(val, bool) and not (types == bool or (isinstance(types, tuple) and bool in types)):
        raise_error(ERR_VALIDATION, f"field {name} has wrong type")
    return val


def req_enum(body, name, allowed, allow_null=False):
    val = req_field(body, name, str, allow_null=allow_null)
    if val is None:
        return val
    if val not in allowed:
        raise_error(ERR_VALIDATION, f"field {name} must be one of {sorted(allowed)}")
    return val


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str) or val not in allowed:
        raise_error(ERR_VALIDATION, f"field {name} must be one of {sorted(allowed)}")
    return val


def req_int(body, name, minimum=None):
    val = req_field(body, name, int)
    if minimum is not None and val < minimum:
        raise_error(ERR_VALIDATION, f"field {name} must be >= {minimum}")
    return val


def opt_int(body, name, default=None, minimum=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, int) or isinstance(val, bool):
        raise_error(ERR_VALIDATION, f"field {name} must be an integer")
    if minimum is not None and val < minimum:
        raise_error(ERR_VALIDATION, f"field {name} must be >= {minimum}")
    return val


def opt_num(body, name, default=None):
    """Numeric field that may be int or float (not bool)."""
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise_error(ERR_VALIDATION, f"field {name} must be a number")
    return val


def opt_list(body, name, default=None):
    if name not in body or body[name] is None:
        return default if default is not None else []
    val = body[name]
    if not isinstance(val, list):
        raise_error(ERR_VALIDATION, f"field {name} must be an array")
    return val


def check_enum_subset(values, allowed, field_name):
    for v in values:
        if not isinstance(v, str) or v not in allowed:
            raise_error(ERR_VALIDATION, f"field {field_name} contains invalid value: {v}")


# ---------------------------------------------------------------------------
# Lookup and pagination
# ---------------------------------------------------------------------------

def get_or_404(collection, rid):
    from db import db
    rec = db[collection].get(rid)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"{collection[:-1]} not found: {rid}")
    return rec


def paginate(items, args):
    """Offset pagination per PRD 2.3. Sorts by created_at ASC first."""
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
        if limit < 1 or limit > 100:
            raise ValueError
    except (TypeError, ValueError):
        raise_error(ERR_VALIDATION, "limit must be an integer between 1 and 100")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
        if offset < 0:
            raise ValueError
    except (TypeError, ValueError):
        raise_error(ERR_VALIDATION, "offset must be a non-negative integer")
    items = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(items)
    page = items[offset:offset + limit]
    return page, total, limit, offset


def apply_filters(items, args, filterable):
    """Filter records by query params that mirror field names."""
    out = []
    for rec in items:
        ok = True
        for f in filterable:
            v = args.get(f, None)
            if v is not None and str(rec.get(f)) != v:
                ok = False
                break
        if ok:
            out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Record stamping (PRD 2.4)
# ---------------------------------------------------------------------------

def stamp_new(rec):
    rec["id"] = new_id()
    rec["created_at"] = now_ts()
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD 2.4/2.9)."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1
    return rec
