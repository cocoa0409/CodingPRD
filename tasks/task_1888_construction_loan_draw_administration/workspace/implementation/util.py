"""Body field validation, dates, decimal math, and pagination helpers."""

from datetime import date
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from flask import request

from errors import ApiError


def get_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _bad(name, why="missing or invalid"):
    raise ApiError("ERR_INVALID_REQUEST", f"Field '{name}': {why}")


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        _bad(name)
    return v


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        _bad(name)
    return v


def _as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(name)
    if isinstance(v, float):
        if not v.is_integer():
            _bad(name, "must be an integer")
        v = int(v)
    return v


def req_int(body, name, min_value=None):
    if name not in body or body[name] is None:
        _bad(name)
    v = _as_int(body[name], name)
    if min_value is not None and v < min_value:
        _bad(name, f"must be >= {min_value}")
    return v


def opt_int(body, name, default=None, min_value=None):
    if name not in body or body[name] is None:
        return default
    v = _as_int(body[name], name)
    if min_value is not None and v < min_value:
        _bad(name, f"must be >= {min_value}")
    return v


def _as_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(name, "must be a number")
    return float(v)


def req_num(body, name):
    if name not in body or body[name] is None:
        _bad(name)
    return _as_num(body[name], name)


def opt_num(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return _as_num(body[name], name)


def req_enum(body, name, allowed):
    v = req_str(body, name)
    if v not in allowed:
        _bad(name, f"must be one of {sorted(allowed)}")
    return v


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    return req_enum(body, name, allowed)


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        _bad(name, "must be a boolean")
    return v


def parse_date_str(v, name):
    """Validate an ISO date string; return the original string."""
    if not isinstance(v, str):
        _bad(name, "must be an ISO date string")
    try:
        date.fromisoformat(v)
    except ValueError:
        _bad(name, "must be a valid ISO 8601 date (YYYY-MM-DD)")
    return v


def req_date(body, name):
    v = body.get(name)
    if v is None:
        _bad(name)
    return parse_date_str(v, name)


def opt_date(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return parse_date_str(body[name], name)


def to_date(s):
    return date.fromisoformat(s)


def day_count(convention, start, end):
    """Days in [start, end) per the loan's day-count convention (PRD §3.8)."""
    if convention == "ACTUAL_360":
        return (end - start).days
    # THIRTY_360 (US)
    d1 = min(start.day, 30)
    d2 = min(end.day, 30)
    if end.day == 31 and start.day >= 30:
        d2 = 30
    return 360 * (end.year - start.year) + 30 * (end.month - start.month) + (d2 - d1)


def round_half_up(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_int(dec):
    return int(Decimal(dec).to_integral_value(rounding=ROUND_FLOOR))


def pct2(dec):
    return float(Decimal(dec).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def dec_num(x):
    """Exact Decimal for a JSON numeric percent (avoids float artifacts)."""
    return Decimal(str(x))


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items_sorted):
    limit, offset = pagination_params()
    total = len(items_sorted)
    return items_sorted[offset : offset + limit], total, limit, offset


def sort_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_order"]))
