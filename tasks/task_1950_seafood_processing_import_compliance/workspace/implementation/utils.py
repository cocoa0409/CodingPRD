"""Decimal precision, datetime parsing/formatting, request body field getters."""
from calendar import monthrange
from datetime import datetime, timezone

from decimal import Decimal, ROUND_HALF_UP
from flask import request

from errors import ApiError, ERR_VALIDATION_FAILED


# ---------------------------------------------------------------- decimals
D3 = Decimal("0.001")
D2 = Decimal("0.01")
D1 = Decimal("0.1")


def q3(d):
    return Decimal(d).quantize(D3, rounding=ROUND_HALF_UP)


def q2(d):
    return Decimal(d).quantize(D2, rounding=ROUND_HALF_UP)


def q1(d):
    return Decimal(d).quantize(D1, rounding=ROUND_HALF_UP)


def q0_int(d):
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec_of(v):
    """Convert an int/float/str JSON number to Decimal; rejects bool/nan/inf."""
    if isinstance(v, bool):
        raise ValueError("bool is not a number")
    d = Decimal(str(v))
    if d.is_nan() or d.is_infinite():
        raise ValueError("not a finite number")
    return d


# ---------------------------------------------------------------- datetimes
def parse_dt(v):
    if not isinstance(v, str):
        raise ValueError("not an ISO8601 string")
    t = v.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt):
    """Canonical ISO UTC; 3 fractional digits only when nonzero."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        return "%s.%03dZ" % (base, dt.microsecond // 1000)
    return base + "Z"


def iso_z3(dt):
    """ISO UTC always with three fractional digits (created_at/updated_at)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def add_months(dt, months):
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    d = min(dt.day, monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------- body fields
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION_FAILED, "Request body must be a JSON object", 400)
    return data


def _missing(name):
    return ApiError(ERR_VALIDATION_FAILED, "Missing required field: %s" % name, 400)


def _bad(name, why="invalid value"):
    return ApiError(ERR_VALIDATION_FAILED, "Field %s: %s" % (name, why), 400)


def req_str(body, name):
    v = body.get(name)
    if v is None:
        raise _missing(name)
    if not isinstance(v, str):
        raise _bad(name, "must be a string")
    return v


def opt_str(body, name, default=None):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, str):
        raise _bad(name, "must be a string")
    return v


def req_bool(body, name):
    v = body.get(name)
    if v is None:
        raise _missing(name)
    if not isinstance(v, bool):
        raise _bad(name, "must be a boolean")
    return v


def opt_bool(body, name, default=None):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise _bad(name, "must be a boolean")
    return v


def req_int(body, name):
    v = body.get(name)
    if v is None:
        raise _missing(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise _bad(name, "must be an integer")
    return v


def req_num(body, name):
    v = body.get(name)
    if v is None:
        raise _missing(name)
    try:
        return dec_of(v)
    except (ValueError, ArithmeticError):
        raise _bad(name, "must be a number")


def opt_num(body, name, default=None):
    v = body.get(name)
    if v is None:
        return default
    try:
        return dec_of(v)
    except (ValueError, ArithmeticError):
        raise _bad(name, "must be a number")


def req_enum(body, name, allowed):
    v = body.get(name)
    if v is None:
        raise _missing(name)
    if not isinstance(v, str) or v not in allowed:
        raise _bad(name, "must be one of %s" % ",".join(sorted(allowed)))
    return v


def opt_enum(body, name, allowed, default=None):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        raise _bad(name, "must be one of %s" % ",".join(sorted(allowed)))
    return v


def req_dt(body, name):
    v = body.get(name)
    if v is None:
        raise _missing(name)
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise _bad(name, "must be an ISO8601 datetime")


def opt_dt(body, name, default=None):
    v = body.get(name)
    if v is None:
        return default
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise _bad(name, "must be an ISO8601 datetime")


def req_num_list(body, name):
    v = body.get(name)
    if v is None:
        raise _missing(name)
    if not isinstance(v, list):
        raise _bad(name, "must be an array of numbers")
    out = []
    for item in v:
        try:
            out.append(dec_of(item))
        except (ValueError, ArithmeticError):
            raise _bad(name, "must be an array of numbers")
    return out


def opt_str_list(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, list) or any(not isinstance(i, str) for i in v):
        raise _bad(name, "must be an array of strings")
    return list(v)


# ---------------------------------------------------------------- pagination
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw, 10)
        except (ValueError, TypeError):
            raise ApiError(ERR_VALIDATION_FAILED, "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError(ERR_VALIDATION_FAILED, "limit must be between 1 and 100", 400)
    if offset_raw is not None:
        try:
            offset = int(offset_raw, 10)
        except (ValueError, TypeError):
            raise ApiError(ERR_VALIDATION_FAILED, "offset must be an integer", 400)
        if offset < 0:
            raise ApiError(ERR_VALIDATION_FAILED, "offset must be >= 0", 400)
    return limit, offset


def sort_items(items):
    """List endpoints sort by creation timestamp ascending (insertion tiebreak)."""
    return sorted(items, key=lambda e: (e["_created_dt"], e["_seq"]))


def paginate(items):
    limit, offset = parse_pagination()
    ordered = sort_items(items)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta
