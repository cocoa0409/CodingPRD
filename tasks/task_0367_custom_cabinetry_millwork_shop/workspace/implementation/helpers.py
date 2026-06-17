"""Shared validation / parsing / pagination helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request
from errors import err
from db import store, now_iso


# --------------------------------------------------------------------------
# Money / rounding
# --------------------------------------------------------------------------
def round_half_up_div(numerator, denominator=10000):
    """round_half_up(numerator / denominator) -> int. Sign-preserving.

    Used for cents * bps / 10000 style steps. ROUND_HALF_UP on Decimal rounds
    away from zero for .5 of positive numbers and toward more-negative for
    negatives; we want magnitude-based half-up that preserves sign, which is
    exactly Decimal ROUND_HALF_UP semantics (0.5 -> 1, -0.5 -> -1).
    """
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


# --------------------------------------------------------------------------
# Body parsing
# --------------------------------------------------------------------------
def get_body():
    if request.method in ("GET", "DELETE"):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_str(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return v


def require_int(body, field, required=True, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    v = body[field]
    # bool is a subclass of int in Python; reject it for integer fields
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s" % (field, maximum))
    return v


def require_bool(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return v


def require_enum(body, field, allowed, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    v = body[field]
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def parse_datetime(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an ISO8601 string" % field)
    dt = _parse_iso(v)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "Field %s must be a valid ISO8601 datetime" % field)
    return dt


def _parse_iso(s):
    if not isinstance(s, str):
        return None
    raw = s.strip()
    txt = raw
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_stored_dt(value):
    """Parse a stored ISO string (or None) back to an aware datetime."""
    if value is None:
        return None
    return _parse_iso(value)


# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_PAGINATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION_PAGINATION", "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_PAGINATION", "offset must be >= 0")
        if offset < 0:
            raise err("ERR_VALIDATION_PAGINATION", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items already sorted; return the page slice."""
    return items[offset:offset + limit]


def sort_by_created(records):
    """Sort by created_at asc, tie-broken by stable seq."""
    return sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
