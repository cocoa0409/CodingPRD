"""Payload schema validators (PRD 2.7 stage 5) and pagination parsing (2.3)."""
from datetime import datetime

from flask import request

from db import parse_dt
from errors import raise_err

_MISSING = object()


def body():
    """JSON request body as a dict; anything else behaves as empty."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _bad(key, why):
    raise_err("ERR_VALIDATION", "Invalid field '%s': %s" % (key, why))


def req_str(d, key):
    v = d.get(key, _MISSING)
    if v is _MISSING:
        _bad(key, "required field missing")
    if not isinstance(v, str):
        _bad(key, "must be a string")
    return v


def opt_str(d, key, default=None):
    v = d.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    if not isinstance(v, str):
        _bad(key, "must be a string")
    return v


def req_int(d, key, min=None, max=None):
    v = d.get(key, _MISSING)
    if v is _MISSING:
        _bad(key, "required field missing")
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(key, "must be an integer")
    if min is not None and v < min:
        _bad(key, "must be >= %d" % min)
    if max is not None and v > max:
        _bad(key, "must be <= %d" % max)
    return v


def opt_int(d, key, default=None, min=None, max=None):
    v = d.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    return req_int(d, key, min=min, max=max)


def req_number(d, key, min=None):
    v = d.get(key, _MISSING)
    if v is _MISSING:
        _bad(key, "required field missing")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(key, "must be a number")
    if min is not None and v < min:
        _bad(key, "must be >= %s" % min)
    return v


def req_enum(d, key, values):
    v = req_str(d, key)
    if v not in values:
        _bad(key, "must be one of %s" % ", ".join(values))
    return v


def opt_enum(d, key, values, default=None):
    v = d.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    return req_enum(d, key, values)


def req_dt(d, key):
    v = req_str(d, key)
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        _bad(key, "must be an ISO 8601 timestamp")


def opt_dt(d, key, default=None):
    v = d.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    return req_dt(d, key)


def req_date(d, key):
    """YYYY-MM-DD calendar date."""
    v = req_str(d, key)
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        _bad(key, "must be a YYYY-MM-DD date")


def pagination():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0 (PRD 2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err("ERR_VALIDATION", "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise_err("ERR_VALIDATION", "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise_err("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset
