"""Body parsing, type/enum validation, pagination parsing, and numeric helpers."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR
from flask import request

import errors

# ----------------------------------------------------------------------------
# Body parsing
# ----------------------------------------------------------------------------

def get_body():
    """Return the JSON body as a dict; ERR_INVALID_REQUEST on malformed/non-object."""
    if request.method in ("GET", "DELETE"):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # An empty body is acceptable for no-input action endpoints.
        if not request.data:
            return {}
        raise errors.err(errors.ERR_INVALID_REQUEST, "malformed JSON body")
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "missing required field: %s" % field)
    return body[field]


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def check_number(v, field):
    if not is_number(v):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be a number" % field)
    return v


def check_int(v, field):
    if not is_int(v):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % field)
    return v


def check_str(v, field, non_empty=False):
    if not isinstance(v, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be a string" % field)
    if non_empty and v.strip() == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be non-empty" % field)
    return v


def check_bool(v, field):
    if not isinstance(v, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be a boolean" % field)
    return v


def check_enum(v, field, allowed):
    if v not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "%s must be one of %s" % (field, sorted(allowed)))
    return v


# ----------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ----------------------------------------------------------------------------
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def parse_pagination():
    """Return (limit, offset); ERR_VALIDATION_PAGINATION if out of bounds."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_VALIDATION_PAGINATION, "limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise errors.err(errors.ERR_VALIDATION_PAGINATION, "limit out of bounds")

    if offset_raw is None:
        offset = OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_VALIDATION_PAGINATION, "offset must be an integer")
        if offset < 0:
            raise errors.err(errors.ERR_VALIDATION_PAGINATION, "offset out of bounds")

    return limit, offset


def paginate(items, limit, offset):
    """Return (page_items, total_count). items must already be sorted."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


# ----------------------------------------------------------------------------
# Numeric / money helpers (PRD §2.8)
# ----------------------------------------------------------------------------

def round_half_up(value):
    """Round a numeric value to a whole integer, half up."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def kwh_3(value):
    """Quantize a kWh quantity to 3 decimal places (kept before cents rounding)."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return d.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def floor_to_tenth(value):
    """Truncate (floor) a kW value down to a whole multiple of 0.1 kW."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return d.quantize(Decimal("0.1"), rounding=ROUND_FLOOR)
