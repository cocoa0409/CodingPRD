"""Parsing, validation, rounding, and pagination helpers.

Structural request validation surfaces ERR_INVALID_REQUEST (HTTP 400) per the
scaffold error catalog and validation priority 23.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError


def invalid(field, msg=None):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg or f"Invalid or missing field: {field}")


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up_cents(value):
    """Round a Decimal to the nearest integer cent, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round a Decimal to two decimal places, half-up."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def minutes_between(start, end):
    """Whole minutes between two instants (floor)."""
    return int((end - start).total_seconds() // 60)


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            invalid("body", "Request body must be valid JSON")
        if not isinstance(data, dict):
            invalid("body", "Request body must be a JSON object")
        return data
    return {}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v.strip():
        invalid(field, f"Missing or invalid required field: {field}")
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if not _is_int(v):
        invalid(field, f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        invalid(field, f"Field {field} must be >= {minimum}")
    return v


def opt_int(data, field, minimum=None):
    if field not in data or data[field] is None:
        return None
    return req_int(data, field, minimum)


def req_num(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        invalid(field, f"Field {field} must be a number")
    return v


def req_enum(data, field, choices):
    v = data.get(field)
    if v not in choices:
        invalid(field, f"Field {field} must be one of {sorted(choices)}")
    return v


def req_dt(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        invalid(field, f"Field {field} must be an ISO 8601 timestamp")
    try:
        return parse_dt(v)
    except Exception:
        invalid(field, f"Field {field} must be an ISO 8601 timestamp")


def opt_dt(data, field):
    if field not in data or data[field] is None:
        return None
    return req_dt(data, field)


def pagination_args():
    """limit/offset query parameters with scaffold defaults (10 / 0; 1..100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("limit", "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("offset", "offset must be an integer")
    if limit < 1 or limit > 100:
        invalid("limit", "limit must be between 1 and 100")
    if offset < 0:
        invalid("offset", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Slice a pre-sorted list and return (page, total_count)."""
    total = len(items)
    return items[offset : offset + limit], total


def dec(value):
    """Exact Decimal from a JSON number (avoids binary float artifacts)."""
    return Decimal(str(value))
