"""Shared validation helpers and pure calculation primitives."""
from decimal import Decimal, ROUND_HALF_UP
from errors import ApiError
from db import parse_iso


def round_half_up_cents(value):
    """Round a Decimal or numeric to integer cents, half-up."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(value):
    """Round to 4 decimal places, half-up. Returns float for JSON serialization."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {f}")


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 400,
                       f"Field {field} must be one of {sorted(allowed)}")
    return v


def optional_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return require_enum(body, field, allowed)


def require_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be <= {maximum}")
    return v


def require_positive_int(body, field):
    return require_int(body, field, minimum=1)


def require_nonneg_int(body, field):
    return require_int(body, field, minimum=0)


def optional_int(body, field, minimum=None, maximum=None, default=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum=minimum, maximum=maximum)


def require_number(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a number")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be <= {maximum}")
    return v


def optional_number(body, field, minimum=None, maximum=None, default=None):
    if field not in body or body[field] is None:
        return default
    return require_number(body, field, minimum=minimum, maximum=maximum)


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a non-empty string")
    return v


def optional_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return require_string(body, field)


def require_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a boolean")
    return v


def optional_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return require_bool(body, field)


def require_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be an ISO8601 string")
    try:
        return parse_iso(v)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} is not a valid ISO8601 timestamp")


def optional_datetime(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return require_datetime(body, field)


def parse_pagination(args):
    """limit/offset query params with defaults limit=10 min=1 max=100 offset=0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def occ_check(body, field, current_version):
    """OCC: field is required; mismatch -> ERR_STALE_VERSION (412)."""
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    if v != current_version:
        raise ApiError("ERR_STALE_VERSION", 412,
                       f"Stale version: expected {v}, current {current_version}")
