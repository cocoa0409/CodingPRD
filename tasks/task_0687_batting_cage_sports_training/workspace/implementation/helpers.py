"""Shared request-handling helpers: body parsing, field validation, pagination,
lookups, and common-field initialization.
"""
from flask import request

from clock import clock, parse_iso
from db import db, new_id, iso_ts
from errors import err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_VALIDATION


def get_json_body():
    """Return the JSON body as a dict (empty dict if none / not an object)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, "Invalid value for %s" % field)


def as_int(value, field, error=ERR_INVALID_REQUEST):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(error, "%s must be an integer" % field)
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3) — limit default 10 (1..100), offset default 0.
# Out-of-bounds / non-integer -> ERR_VALIDATION.
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_VALIDATION, "limit out of bounds")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise err(ERR_VALIDATION, "offset out of bounds")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at asc (stable by insertion seq), slice, build meta."""
    ordered = sorted(items, key=lambda x: (x["created_at"], x.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


# ---------------------------------------------------------------------------
# Lookups (raise ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def lookup(collection, resource_id):
    obj = collection.get(resource_id)
    if obj is None:
        raise err(ERR_NOT_FOUND, "Resource not found")
    return obj


# ---------------------------------------------------------------------------
# Common-field initialization (PRD 2.4)
# ---------------------------------------------------------------------------
def base_common_fields():
    ts = iso_ts(clock.now())
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def waiver_common_fields():
    # Waiver: id + created_at only (PRD 2.4).
    ts = iso_ts(clock.now())
    return {
        "id": new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
