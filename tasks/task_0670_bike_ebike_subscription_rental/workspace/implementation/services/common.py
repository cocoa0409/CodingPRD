"""Common-field stamping, request-body validation utilities, pagination."""
from flask import request

from db import db, iso_ms
from clock import clock
from errors import err, ERR_INVALID_REQUEST


def stamp_create(rec, common_fields=True):
    """Apply server-managed common fields on creation.

    PRD §2.4: id (UUID, no prefix), created_at (ISO ms), and for full-common-field
    entities updated_at + version (begins at initial value = 1). InspectionReport
    carries only id + created_at (common_fields=False)."""
    now = clock.now()
    rec["id"] = db.new_id()
    rec["created_at"] = iso_ms(now)
    rec["_seq"] = db.next_seq()
    if common_fields:
        rec["updated_at"] = iso_ms(now)
        rec["version"] = 1
    return rec


def touch(rec):
    """PRD §2.5: on every mutation refresh updated_at and increment version by one."""
    rec["updated_at"] = iso_ms(clock.now())
    rec["version"] = rec.get("version", 1) + 1


# ---- request body parsing ----

def get_json_body():
    """Return the JSON body as a dict; missing/invalid body -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Malformed JSON body.")
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


def require_nonneg_int(value, field):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise err(ERR_INVALID_REQUEST, "%s must be a non-negative integer." % field)
    return value


def require_string(value, field):
    if not isinstance(value, str) or value == "":
        raise err(ERR_INVALID_REQUEST, "%s must be a non-empty string." % field)
    return value


# ---- pagination (SCAFFOLD §1.0 / PRD §2.3) ----

def parse_pagination():
    """Return (limit, offset). limit default 10, min 1, max 100. offset default 0."""
    args = request.args
    limit = _parse_int_param(args.get("limit"), default=10)
    offset = _parse_int_param(args.get("offset"), default=0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_int_param(raw, default):
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def paginate(records, limit, offset):
    """Sort by created_at ascending (insertion seq tiebreak) then slice."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
