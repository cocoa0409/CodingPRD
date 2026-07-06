"""Common record helpers: timestamps/version, pagination, input coercion."""
from flask import request

import errors
from db import db, new_id, now_iso

# Pagination defaults (PRD §2.3 / SCAFFOLD §1.0).
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def make_record(extra=None, common_fields=True):
    """Create a base record dict with id/created_at (+ updated_at/version when
    common_fields). ServicePlan passes common_fields=False (PRD §2.4)."""
    rec = {"id": new_id(), "created_at": now_iso()}
    if common_fields:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    """Refresh updated_at and bump version on any mutation (PRD §2.4, §2.5)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    """Strip internal-only fields from a record before serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# --- Input parsing ----------------------------------------------------------
def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise errors.err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
        return data
    return {}


def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")


def as_int(body, name, required=False, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and val < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} below minimum {minimum}")
    if maximum is not None and val > maximum:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} above maximum {maximum}")
    return val


def as_str(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = body[name]
    if not isinstance(val, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a string")
    return val


def as_bool(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return val


def as_enum(body, name, choices, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = body[name]
    if val not in choices:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(choices)}")
    return val


def as_array(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return list(default) if default is not None else []
    val = body[name]
    if not isinstance(val, list):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an array")
    return val


# --- Pagination -------------------------------------------------------------
def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = PAGE_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit out of range")
    if offset_raw is None:
        offset = PAGE_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(records):
    """Sort by created_at ascending (insertion seq as deterministic tie-break),
    apply limit/offset, return (page_records, pagination_meta)."""
    limit, offset = get_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
