"""Request body parsing, field validation, pagination helpers."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

from flask import request

from errors import err


def get_body():
    """Parse JSON body, return {} when absent. Malformed JSON -> ERR_INVALID_REQUEST."""
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return body[field]


def opt(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return body[field]


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return value


def as_enum(value, field, allowed):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))
    return value


def int_min(value, field, minimum):
    v = as_int(value, field)
    if v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (field, minimum))
    return v


def int_range(value, field, lo, hi):
    v = as_int(value, field)
    if v < lo or v > hi:
        raise err("ERR_INVALID_REQUEST", "Field %s must be between %s and %s" % (field, lo, hi))
    return v


def frac(value, field, lo=0.0, hi=1.0, lo_inclusive=True, hi_inclusive=True):
    v = as_number(value, field)
    if lo_inclusive and v < lo:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (field, lo))
    if not lo_inclusive and v <= lo:
        raise err("ERR_INVALID_REQUEST", "Field %s must be > %s" % (field, lo))
    if hi_inclusive and v > hi:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s" % (field, hi))
    if not hi_inclusive and v >= hi:
        raise err("ERR_INVALID_REQUEST", "Field %s must be < %s" % (field, hi))
    return v


def parse_pagination():
    """Parse limit/offset query params. Out-of-range -> ERR_VALIDATION (400)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "offset must be >= 0")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Sort already done by caller. Slice items by limit/offset, return (page, total)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


# --- Rounding helpers (monetary; integer cents) ---------------------------------

def round_half_up(value):
    """Round a numeric (int/float) to nearest integer cents, half up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_cents(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def ceil_cents(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_CEILING))
