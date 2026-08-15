"""Shared helpers: body parsing, field validation, pagination, mutation touch.

Body-handling conventions (PRD 2.9): unknown fields and system-managed fields
supplied in a request body are ignored, not rejected.
"""
import json
from decimal import Decimal, ROUND_HALF_UP

from flask import g, request

from db import db, parse_dt, now_iso
from errors import ApiError

TWO_PLACES = Decimal("0.01")


# ---------------------------------------------------------------- decimals
def dec(v):
    """Coerce a JSON number (int/float/Decimal) to Decimal exactly."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise ValueError("bool is not a number")
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        return Decimal(str(v))
    raise ValueError(f"not a number: {v!r}")


def round2(x):
    """Round a Decimal to 2 decimal places, half-up (PRD 2.7)."""
    return x.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ---------------------------------------------------------------- requests
def get_body():
    """Parse the JSON request body. Absent body -> {}. Malformed -> 400."""
    raw = request.get_data()
    if not raw:
        return {}
    try:
        data = json.loads(raw, parse_float=Decimal)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body is not valid JSON.")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object.")
    return data


def _fail(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str):
        _fail(f"Field '{key}' is required and must be a string.")
    return v


def req_str_nonempty(body, key):
    v = req_str(body, key)
    if v == "":
        _fail(f"Field '{key}' must be non-empty.")
    return v


def opt_str(body, key, default=None):
    v = body.get(key, default)
    if v is None:
        return None
    if not isinstance(v, str):
        _fail(f"Field '{key}' must be a string.")
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        _fail(f"Field '{key}' must be one of {sorted(allowed)}.")
    return v


def opt_enum(body, key, allowed, default=None):
    if key not in body or body[key] is None:
        return default
    return req_enum(body, key, allowed)


def is_number(v):
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def req_number(body, key):
    v = body.get(key)
    if not is_number(v):
        _fail(f"Field '{key}' is required and must be a number.")
    return dec(v)


def opt_number(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    return req_number(body, key)


def req_int(body, key):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        _fail(f"Field '{key}' is required and must be an integer.")
    return v


def req_datetime(body, key):
    """Required ISO-8601 datetime string. Stored verbatim; parsed for checks."""
    v = body.get(key)
    if not isinstance(v, str):
        _fail(f"Field '{key}' is required and must be an ISO-8601 datetime string.")
    try:
        parse_dt(v)
    except Exception:
        _fail(f"Field '{key}' must be a valid ISO-8601 datetime.")
    return v


def req_str_list(body, key):
    v = body.get(key)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        _fail(f"Field '{key}' is required and must be an array of strings.")
    return v


def opt_int_field(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    return req_int(body, key)


# ---------------------------------------------------------------- pagination
def pagination_params():
    """limit defaults to 10, clamped to [1,100]; offset defaults to 0, min 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            _fail("Query parameter 'limit' must be an integer.")
        limit = max(1, min(100, limit))
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            _fail("Query parameter 'offset' must be an integer.")
        offset = max(0, offset)
    return limit, offset


def sorted_entities(items):
    """Default list ordering: created_at ascending (insertion-order tiebreak)."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def page_of(items):
    limit, offset = pagination_params()
    ordered = sorted_entities(items)
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return [serialize(e) for e in page], limit, offset, total


def serialize(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


# ---------------------------------------------------------------- mutation
def touch(coll, ent):
    """Bump version and refresh updated_at, at most once per entity per request.

    PRD 2.4: version increments by exactly one on every modification; compound
    operations bump each affected entity once.
    """
    dirty = getattr(g, "_dirty", None)
    key = (id(coll), ent["id"])
    if dirty is not None:
        if key in dirty:
            return
        dirty.add(key)
    ent["version"] += 1
    ent["updated_at"] = now_iso()


def get_or_404(coll, rid):
    ent = coll.get(rid)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Resource not found: {rid}")
    return ent
