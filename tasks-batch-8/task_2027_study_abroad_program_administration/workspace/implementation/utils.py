"""Shared validation and calculation helpers."""

import math
from datetime import datetime, timezone
from errors import invalid_request


def parse_dt(value, field_name):
    """Parse an ISO 8601 datetime string to an aware datetime. Raises ERR_INVALID_REQUEST on failure."""
    if not isinstance(value, str):
        raise invalid_request(f"{field_name} must be an ISO 8601 string")
    try:
        s = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise invalid_request(f"{field_name} is not a valid ISO 8601 datetime")


def require_field(body, field):
    if field not in body or body[field] is None:
        raise invalid_request(f"Missing required field: {field}")
    return body[field]


def require_string(body, field):
    v = require_field(body, field)
    if not isinstance(v, str):
        raise invalid_request(f"{field} must be a string")
    return v


def require_int(body, field):
    v = require_field(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"{field} must be an integer")
    return v


def require_number(body, field):
    v = require_field(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request(f"{field} must be a number")
    return v


def require_enum(body, field, allowed):
    v = require_field(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise invalid_request(f"{field} must be one of {sorted(allowed)}")
    return v


def require_bool(body, field):
    v = require_field(body, field)
    if not isinstance(v, bool):
        raise invalid_request(f"{field} must be a boolean")
    return v


def round_half_up_step(value, step):
    """Round value to nearest multiple of step, ties away from zero (round half up)."""
    # value / step, round half away from zero, multiply back
    quotient = value / step
    rounded = math.floor(quotient + 0.5) if quotient >= 0 else math.ceil(quotient - 0.5)
    return rounded * step


def round_credit(host_credits, factor):
    """Per-course credit conversion: raw = host_credits * factor; round to nearest 0.5 half-up."""
    raw = host_credits * factor
    return round_half_up_step(raw, 0.5)


def parse_pagination(args):
    """Parse limit/offset query params with defaults limit=10, min=1, max=100, offset=0."""
    limit_s = args.get("limit")
    offset_s = args.get("offset")
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (ValueError, TypeError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (ValueError, TypeError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset
