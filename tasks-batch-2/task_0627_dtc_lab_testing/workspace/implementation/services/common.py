"""Shared helpers: lookups, request-body validation, serialization."""
from flask import request

import db
from errors import err

# Fields stripped from serialized output (internal bookkeeping).
_INTERNAL = {"_seq"}


def serialize(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if k not in _INTERNAL}


def serialize_list(recs):
    return [serialize(r) for r in recs]


def get_json():
    """Parse JSON body; tolerate empty body for action endpoints."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_found(table, rec_id):
    """Existence check (priority 4). Returns the record or raises ERR_NOT_FOUND."""
    rec = db.get(table, rec_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource %s not found" % rec_id)
    return rec


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "Invalid value for %s: %r" % (field, value))


def require_str(body, field, required=True):
    v = body.get(field)
    if v is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    if not isinstance(v, str) or not v.strip():
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return v


def require_int(body, field, required=True, non_negative=True, positive=False):
    v = body.get(field)
    if v is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if positive and v <= 0:
        raise err("ERR_INVALID_REQUEST", "Field %s must be > 0" % field)
    if non_negative and v < 0:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= 0" % field)
    return v


def require_bool(body, field, required=True, default=None):
    v = body.get(field)
    if v is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return v


def require_number(body, field, required=True):
    v = body.get(field)
    if v is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    return v


def pagination_params():
    """limit (default 10, min 1, max 100) and offset (default 0) per PRD §2.3."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(rows):
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, limit, offset, total
