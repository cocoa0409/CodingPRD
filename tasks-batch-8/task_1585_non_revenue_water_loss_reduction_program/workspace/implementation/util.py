"""Validation and pagination helpers."""

from decimal import Decimal

from flask import request

import db
import errors
from errors import ApiError


def D(x):
    return Decimal(str(x))


def _verr(msg):
    return ApiError(errors.ERR_VALIDATION, 422, msg)


def v_str(body, field, required=True, min_len=None, max_len=None):
    val = body.get(field)
    if val is None:
        if required:
            raise _verr("%s is required" % field)
        return None
    if not isinstance(val, str) or isinstance(val, bool) or val == "":
        raise _verr("%s must be a non-empty string" % field)
    if min_len is not None and len(val) < min_len:
        raise _verr("%s must be at least %d characters" % (field, min_len))
    if max_len is not None and len(val) > max_len:
        raise _verr("%s must be at most %d characters" % (field, max_len))
    return val


def v_num(body, field, required=True, gt=None, ge=None, lt=None, le=None):
    val = body.get(field)
    if val is None:
        if required:
            raise _verr("%s is required" % field)
        return None
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise _verr("%s must be a number" % field)
    d = D(val)
    if gt is not None and not d > D(gt):
        raise _verr("%s must be greater than %s" % (field, gt))
    if ge is not None and not d >= D(ge):
        raise _verr("%s must be at least %s" % (field, ge))
    if lt is not None and not d < D(lt):
        raise _verr("%s must be less than %s" % (field, lt))
    if le is not None and not d <= D(le):
        raise _verr("%s must be at most %s" % (field, le))
    return val


def v_int(body, field, required=True, ge=None, le=None):
    val = body.get(field)
    if val is None:
        if required:
            raise _verr("%s is required" % field)
        return None
    if isinstance(val, bool):
        raise _verr("%s must be an integer" % field)
    if isinstance(val, float):
        if not val.is_integer():
            raise _verr("%s must be an integer" % field)
        val = int(val)
    if not isinstance(val, int):
        raise _verr("%s must be an integer" % field)
    if ge is not None and val < ge:
        raise _verr("%s must be at least %s" % (field, ge))
    if le is not None and val > le:
        raise _verr("%s must be at most %s" % (field, le))
    return val


def v_dt(body, field, required=True):
    val = body.get(field)
    if val is None:
        if required:
            raise _verr("%s is required" % field)
        return None
    dt = db.parse_dt(val)
    if dt is None:
        raise _verr("%s must be a valid ISO 8601 datetime" % field)
    return dt


def v_enum(body, field, allowed, required=True, default=None):
    val = body.get(field)
    if val is None:
        if required:
            raise _verr("%s is required" % field)
        return default
    if val not in allowed:
        raise _verr("%s must be one of %s" % (field, ", ".join(allowed)))
    return val


def canon(dt):
    return db.fmt_dt(dt)


def paginate(items):
    """Parse limit/offset from query args; slice items; return (page, meta)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise _verr("limit must be an integer")
        if limit < 1 or limit > 100:
            raise _verr("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise _verr("offset must be an integer")
        if offset < 0:
            raise _verr("offset must be at least 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def sort_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
