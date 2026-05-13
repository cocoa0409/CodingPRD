"""Shared utility functions."""
import re
from decimal import Decimal, ROUND_HALF_UP

from errors import APIError, ERR_BAD_REQUEST


def round_half_up_cents(value) -> int:
    """Round any numeric to the nearest integer using ROUND_HALF_UP."""
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_decimals(value, places: int) -> float:
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    quant = Decimal("1").scaleb(-places)  # 10**-places
    return float(d.quantize(quant, rounding=ROUND_HALF_UP))


def require_field(body, field):
    if body is None or field not in body or body[field] is None:
        raise APIError(ERR_BAD_REQUEST, 422, f"Missing required field: {field}")
    return body[field]


def get_int(body, field, required=True, default=None, min_value=None):
    if body is None or field not in body or body[field] is None:
        if required:
            raise APIError(ERR_BAD_REQUEST, 422, f"Missing required field: {field}")
        return default
    val = body[field]
    if isinstance(val, bool):
        raise APIError(ERR_BAD_REQUEST, 422, f"Field {field} must be integer")
    if not isinstance(val, int):
        # try coerce
        try:
            val = int(val)
        except (ValueError, TypeError):
            raise APIError(ERR_BAD_REQUEST, 422, f"Field {field} must be integer")
    if min_value is not None and val < min_value:
        raise APIError(ERR_BAD_REQUEST, 422, f"Field {field} must be >= {min_value}")
    return val


def get_str(body, field, required=True, default=None, pattern=None, max_len=None):
    if body is None or field not in body or body[field] is None:
        if required:
            raise APIError(ERR_BAD_REQUEST, 422, f"Missing required field: {field}")
        return default
    val = body[field]
    if not isinstance(val, str):
        raise APIError(ERR_BAD_REQUEST, 422, f"Field {field} must be string")
    if pattern and not re.match(pattern, val):
        raise APIError(ERR_BAD_REQUEST, 422, f"Field {field} does not match pattern {pattern}")
    return val


def get_bool(body, field, required=True, default=None):
    if body is None or field not in body or body[field] is None:
        if required:
            raise APIError(ERR_BAD_REQUEST, 422, f"Missing required field: {field}")
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise APIError(ERR_BAD_REQUEST, 422, f"Field {field} must be boolean")
    return val


def get_enum(body, field, allowed, required=True, default=None):
    if body is None or field not in body or body[field] is None:
        if required:
            raise APIError(ERR_BAD_REQUEST, 422, f"Missing required field: {field}")
        return default
    val = body[field]
    if val not in allowed:
        raise APIError(ERR_BAD_REQUEST, 422, f"Field {field} must be one of {sorted(allowed)}")
    return val


def get_pagination(args):
    try:
        limit = int(args.get("limit", 10))
    except (ValueError, TypeError):
        raise APIError(ERR_BAD_REQUEST, 422, "Invalid limit")
    try:
        offset = int(args.get("offset", 0))
    except (ValueError, TypeError):
        raise APIError(ERR_BAD_REQUEST, 422, "Invalid offset")
    if limit < 1 or limit > 100:
        raise APIError(ERR_BAD_REQUEST, 422, "limit must be between 1 and 100")
    if offset < 0:
        raise APIError(ERR_BAD_REQUEST, 422, "offset must be >= 0")
    return limit, offset


def paginate(items, limit: int, offset: int):
    total = len(items)
    window = items[offset:offset + limit]
    return window, total
