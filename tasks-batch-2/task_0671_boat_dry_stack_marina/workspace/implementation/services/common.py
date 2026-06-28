"""Common-field stamping, request-body validation utilities, pagination
(PRD §2.3, §2.4, §2.5)."""
from flask import request

from db import db, iso_ms
from clock import clock
from errors import err, ERR_INVALID_REQUEST, ERR_INVALID_PAGINATION


def stamp_create(rec):
    """Apply server-managed common fields on creation (PRD §2.4).

    id (UUID, no prefix), created_at + updated_at (ISO ms), version begins at 1.
    Timestamps use the logical clock (all 'now' references are the logical clock)."""
    now = clock.now()
    rec["id"] = db.new_id()
    rec["created_at"] = iso_ms(now)
    rec["updated_at"] = iso_ms(now)
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """PRD §2.4/§2.5: on every mutation (direct or cascade) refresh updated_at
    and increment version by one."""
    rec["updated_at"] = iso_ms(clock.now())
    rec["version"] = rec.get("version", 1) + 1


# ---- request body parsing (priority 21, ERR_INVALID_REQUEST) ----

def get_json_body():
    """Return the JSON body as a dict; missing/invalid body -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, "Invalid value for %s." % field)
    return value


def require_string(value, field):
    if not isinstance(value, str) or value == "":
        raise err(ERR_INVALID_REQUEST, "%s must be a non-empty string." % field)
    return value


def require_pos_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise err(ERR_INVALID_REQUEST, "%s must be a positive integer." % field)
    return value


def require_nonneg_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise err(ERR_INVALID_REQUEST, "%s must be a non-negative integer." % field)
    return value


def require_pos_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise err(ERR_INVALID_REQUEST, "%s must be a positive number." % field)
    return value


def require_nonneg_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise err(ERR_INVALID_REQUEST, "%s must be a non-negative number." % field)
    return value


def require_bool(value, field):
    if not isinstance(value, bool):
        raise err(ERR_INVALID_REQUEST, "%s must be a boolean." % field)
    return value


# ---- pagination (SCAFFOLD §1.0 / PRD §2.3) ----

def parse_pagination():
    """Return (limit, offset). limit default 10, min 1, max 100 (inclusive);
    offset default 0, min 0. Out-of-bounds -> ERR_INVALID_PAGINATION (400)."""
    args = request.args
    limit = _parse_int_param(args.get("limit"), default=10)
    offset = _parse_int_param(args.get("offset"), default=0)
    if limit < 1 or limit > 100:
        raise err(ERR_INVALID_PAGINATION, "limit must be in [1, 100].")
    if offset < 0:
        raise err(ERR_INVALID_PAGINATION, "offset must be >= 0.")
    return limit, offset


def _parse_int_param(raw, default):
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        # Non-integer pagination value is out of bounds.
        raise err(ERR_INVALID_PAGINATION, "pagination parameters must be integers.")


def paginate(records, limit, offset):
    """Sort by created_at ascending (insertion seq tiebreak) then slice."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
