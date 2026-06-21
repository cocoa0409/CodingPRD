"""Common-field management and pagination helpers (PRD §2.3, §2.4).

Most resources carry id, created_at, updated_at, version. Two record types are
immutable audit entries carrying only id + created_at: PostAccess and Message
(PRD §2.4).

Whenever the server adjusts a derived field on a resource, that adjustment is
itself a mutation: it refreshes updated_at and increments version (PRD §2.4).
"""
from flask import request

import errors
from db import db, new_id, iso_millis, wall_now


def init_common(rec):
    """Stamp full common fields (id, created_at, updated_at, version)."""
    rec["id"] = new_id()
    now = wall_now()
    rec["created_at"] = iso_millis(now)
    rec["updated_at"] = iso_millis(now)
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    rec["_created_seq"] = rec["_seq"]
    return rec


def init_audit(rec):
    """Stamp audit-only common fields (id, created_at) — PostAccess, Message."""
    rec["id"] = new_id()
    rec["created_at"] = iso_millis(wall_now())
    rec["_seq"] = db.next_seq()
    rec["_created_seq"] = rec["_seq"]
    return rec


def touch(rec):
    """Mark a resource mutated: bump updated_at + version (PRD §2.4)."""
    rec["updated_at"] = iso_millis(wall_now())
    rec["version"] = rec.get("version", 1) + 1


# ---- pagination (PRD §2.3) ----

def parse_pagination():
    """limit default 10 (min 1, max 100); offset default 0.

    Out-of-range / malformed pagination values are a bad request (PRD §2.6).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            errors.fail(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            errors.fail(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            errors.fail(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            errors.fail(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC (stable via _created_seq) then slice (PRD §2.3)."""
    ordered = sorted(items, key=lambda r: r["_created_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ---- request-body parsing (PRD §2.6 priority 6: ERR_INVALID_REQUEST) ----

def get_body():
    """Parse the JSON request body; missing/invalid JSON -> empty dict.

    A non-object JSON body (list, scalar) is a malformed request.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        # An empty body is acceptable for parameter-less POSTs; only reject if
        # raw bytes were present but unparseable.
        if request.data:
            errors.fail(errors.ERR_INVALID_REQUEST, "Request body is not valid JSON")
        return {}
    if not isinstance(data, dict):
        errors.fail(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(body, *names):
    """Every named field must be present and non-null (PRD §2.6)."""
    for name in names:
        if name not in body or body[name] is None:
            errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)


def require_string(body, name):
    val = body.get(name)
    if not isinstance(val, str) or not val.strip():
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % name)
    return val


def require_enum(body, name, allowed):
    val = body.get(name)
    if val not in allowed:
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "Field %s must be one of %s" % (name, sorted(allowed)))
    return val


def optional_enum(body, name, allowed, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if val not in allowed:
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "Field %s must be one of %s" % (name, sorted(allowed)))
    return val


def require_int(body, name, minimum=None):
    val = body.get(name)
    if isinstance(val, bool) or not isinstance(val, int):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    if minimum is not None and val < minimum:
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be >= %s" % (name, minimum))
    return val
