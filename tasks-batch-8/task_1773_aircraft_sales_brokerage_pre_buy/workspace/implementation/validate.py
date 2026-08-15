"""Request body validation (PRD 2.8 priority 4) and pagination parsing (2.3).

Monetary inputs are exactly two-decimal values; prices/deposits must be
positive and cost estimates non-negative (PRD 2.5). Failures raise
ERR_VALIDATION (400). Booking windows are checked by the bookings route with
ERR_BOOKING_WINDOW_INVALID (422).
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import request

from errors import ERR_VALIDATION, raise_error
from util import parse_date, parse_datetime

CENT = Decimal("0.01")


def body() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_error(ERR_VALIDATION, "request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Scalar field validators
# ---------------------------------------------------------------------------

def req_str(b, field):
    if field not in b or b[field] is None:
        raise_error(ERR_VALIDATION, f"{field} is required")
    if not isinstance(b[field], str):
        raise_error(ERR_VALIDATION, f"{field} must be a string")
    return b[field]


def opt_str(b, field, default=None):
    if field not in b or b[field] is None:
        return default
    if not isinstance(b[field], str):
        raise_error(ERR_VALIDATION, f"{field} must be a string")
    return b[field]


def req_bool(b, field):
    if field not in b or b[field] is None:
        raise_error(ERR_VALIDATION, f"{field} is required")
    if not isinstance(b[field], bool):
        raise_error(ERR_VALIDATION, f"{field} must be a boolean")
    return b[field]


def opt_bool(b, field, default=None):
    if field not in b or b[field] is None:
        return default
    if not isinstance(b[field], bool):
        raise_error(ERR_VALIDATION, f"{field} must be a boolean")
    return b[field]


def _int_value(v, field, min_value):
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_VALIDATION, f"{field} must be an integer")
    if min_value is not None and v < min_value:
        raise_error(ERR_VALIDATION, f"{field} must be >= {min_value}")
    return v


def req_int(b, field, min_value=None):
    if field not in b or b[field] is None:
        raise_error(ERR_VALIDATION, f"{field} is required")
    return _int_value(b[field], field, min_value)


def opt_int(b, field, default=None, min_value=None):
    if field not in b or b[field] is None:
        return default
    return _int_value(b[field], field, min_value)


def _money_value(v, field, allow_zero):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_VALIDATION, f"{field} must be a number")
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        raise_error(ERR_VALIDATION, f"{field} must be a number")
    if d.is_nan() or d.is_infinite():
        raise_error(ERR_VALIDATION, f"{field} must be a finite number")
    try:
        quantized = d.quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise_error(ERR_VALIDATION, f"{field} is out of range")
    if d != quantized:
        raise_error(ERR_VALIDATION, f"{field} must have at most two decimal places")
    if allow_zero:
        if d < 0:
            raise_error(ERR_VALIDATION, f"{field} must be non-negative")
    elif d <= 0:
        raise_error(ERR_VALIDATION, f"{field} must be greater than zero")
    return quantized


def req_money(b, field, allow_zero=False):
    if field not in b or b[field] is None:
        raise_error(ERR_VALIDATION, f"{field} is required")
    return _money_value(b[field], field, allow_zero)


def opt_money(b, field, allow_zero=False):
    if field not in b or b[field] is None:
        return None
    return _money_value(b[field], field, allow_zero)


def req_enum(b, field, allowed):
    value = req_str(b, field)
    if value not in allowed:
        raise_error(
            ERR_VALIDATION, f"{field} must be one of {', '.join(allowed)}"
        )
    return value


def opt_enum(b, field, allowed, default=None):
    if field not in b or b[field] is None:
        return default
    return req_enum(b, field, allowed)


def req_datetime(b, field):
    """Return (raw_string, parsed_aware_datetime)."""
    raw = req_str(b, field)
    try:
        return raw, parse_datetime(raw)
    except (ValueError, OverflowError):
        raise_error(ERR_VALIDATION, f"{field} must be an ISO 8601 datetime")


def req_date_str(b, field):
    raw = req_str(b, field)
    try:
        parse_date(raw)
    except (ValueError, OverflowError):
        raise_error(ERR_VALIDATION, f"{field} must be an ISO 8601 date")
    return raw


def opt_nullable_str(b, field):
    """Returns (provided, value): provided is True when the key is present."""
    if field not in b:
        return False, None
    value = b[field]
    if value is not None and not isinstance(value, str):
        raise_error(ERR_VALIDATION, f"{field} must be a string or null")
    return True, value


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10 (min 1, max 100), offset default 0
# ---------------------------------------------------------------------------

def page_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION, "limit must be an integer")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION, "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset
