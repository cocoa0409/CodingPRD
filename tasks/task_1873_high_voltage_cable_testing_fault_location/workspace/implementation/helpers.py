"""Request-shape validators, entity lookup, serialization, pagination."""
from datetime import datetime
from decimal import Decimal

from flask import request

import db
import util
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND


# ---------------------------------------------------------------- body/shape
def body_dict():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return b


def req_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: %s" % name)
    return body[name]


def _bad(name, why):
    raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid field %s: %s" % (name, why))


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str):
        _bad(name, "must be a string")
    return v


def req_int(body, name):
    v = req_field(body, name)
    if not is_int(v):
        _bad(name, "must be an integer")
    return v


def req_num(body, name):
    v = req_field(body, name)
    if not is_num(v):
        _bad(name, "must be a number")
    return v


def req_bool(body, name):
    v = req_field(body, name)
    if not isinstance(v, bool):
        _bad(name, "must be a boolean")
    return v


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], bool):
        _bad(name, "must be a boolean")
    return body[name]


def req_enum(body, name, allowed):
    v = req_field(body, name)
    if v not in allowed:
        _bad(name, "must be one of %s" % "/".join(allowed))
    return v


def req_dt(body, name):
    v = req_field(body, name)
    dt = util.parse_dt(v)
    if dt is None:
        _bad(name, "must be an ISO 8601 datetime")
    return dt


def req_list(body, name):
    v = req_field(body, name)
    if not isinstance(v, list):
        _bad(name, "must be an array")
    return v


# ---------------------------------------------------------------- lookups
def get_or_404(store, oid, what="Resource"):
    rec = store.get(oid) if isinstance(oid, str) else None
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, "%s not found: %s" % (what, oid))
    return rec


# ---------------------------------------------------------------- serialization
def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = util.iso(v)
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def serialize_list(recs):
    return [serialize(r) for r in recs]


# ---------------------------------------------------------------- pagination
def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be >= 0")
    return limit, offset


def sorted_by_creation(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(recs):
    """Sort by created_at ascending, apply limit/offset, return (page, meta)."""
    limit, offset = pagination_params()
    ordered = sorted_by_creation(recs)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
