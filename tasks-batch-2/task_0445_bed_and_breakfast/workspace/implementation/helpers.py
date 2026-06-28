"""Shared helpers: pagination, request body parsing/validation primitives,
entity lookup with inn-scope (left-to-right existence), and serialization.
"""
from flask import request

from errors import err
from db import db


# --------------------------------------------------------------------------- #
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------- #
def paginate_params():
    """limit default 10, min 1, max 100; offset default 0. Bad values -> ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range [1,100]")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def sort_and_page(items, limit, offset):
    """Sort by created_at ASC (insertion seq tiebreak), apply offset/limit."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total


# --------------------------------------------------------------------------- #
# Body parsing
# --------------------------------------------------------------------------- #
def get_json_body():
    """Parse JSON body; absent body is treated as empty object. Malformed JSON
    -> ERR_INVALID_REQUEST."""
    if request.data is None or len(request.data) == 0:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % n)


def as_str(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    v = body[name]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a string" % name)
    return v


def as_int(body, name, required=True, default=None, min_value=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if min_value is not None and v < min_value:
        raise err("ERR_INVALID_REQUEST", "%s must be >= %d" % (name, min_value))
    return v


def as_bool(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return v


def as_enum(body, name, allowed, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    v = body[name]
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, sorted(allowed)))
    return v


def parse_date_field(body, name, required=True, default=None):
    """Validate a YYYY-MM-DD date string. Unparseable -> ERR_INVALID_REQUEST."""
    from datetime import datetime
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    v = body[name]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a date string" % name)
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "%s is not a valid YYYY-MM-DD date" % name)
    return v


# --------------------------------------------------------------------------- #
# Existence lookups, inn-scoped (left-to-right, ERR_NOT_FOUND)
# --------------------------------------------------------------------------- #
def get_inn_or_404(inn_id):
    inn = db.inns.get(inn_id)
    if inn is None:
        raise err("ERR_NOT_FOUND", "Inn not found")
    return inn


def get_scoped_or_404(collection, obj_id, inn_id, label):
    obj = collection.get(obj_id)
    if obj is None or obj.get("inn_id") != inn_id:
        raise err("ERR_NOT_FOUND", "%s not found" % label)
    return obj


def get_booking_scoped_or_404(booking_id, inn_id):
    return get_scoped_or_404(db.bookings, booking_id, inn_id, "Booking")
