"""Parsing, validation, rounding, and pagination helpers."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError


def round_half_up_cents(value):
    """Round a Decimal to the nearest integer cent, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_hours(value):
    """Round a Decimal hour quantity to two decimal places, half-up."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_decimal(value):
    """Convert an int/float/str to Decimal via str to avoid float artifacts."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
        return data
    return {}


def required(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    return data[field]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def as_int(v, field):
    if not _is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an integer")
    return v


def as_str(v, field):
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a string")
    return v


def as_num(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a number")
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a boolean")
    return v


def as_list(v, field):
    if not isinstance(v, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an array")
    return v


def pagination_args():
    """limit/offset query parameters with scaffold defaults (10 / 0, min 1, max 100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate_sorted(items):
    """Sort by created_at asc and apply limit/offset.

    Returns (page_items, total_count, limit, offset)."""
    limit, offset = pagination_args()
    items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return page, total, limit, offset
