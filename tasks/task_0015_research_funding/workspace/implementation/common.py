"""Common helpers — pagination, decimal/money helpers, validation utilities."""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

from clock import clock
from errors import ERR_INVALID_INPUT, ERR_INVALID_PAGINATION_PARAMETERS, raise_error


def parse_pagination():
    args = request.args
    limit_raw = args.get("limit", "10")
    offset_raw = args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_PAGINATION_PARAMETERS, "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise_error(ERR_INVALID_PAGINATION_PARAMETERS, "limit must be in [1,100]; offset >= 0")
    return limit, offset


def paginate_list(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def to_decimal(value, fallback=None):
    """Convert a numeric value to Decimal preserving precision."""
    if value is None:
        return fallback
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        raise_error(ERR_INVALID_INPUT, "expected numeric value")


def round_money(value) -> Decimal:
    return to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_rate(value) -> Decimal:
    return to_decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def money_to_json(value):
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = to_decimal(value)
    return float(round_money(value))


def rate_to_json(value):
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = to_decimal(value)
    return float(round_rate(value))


def stamp_create(record):
    """Set created_at, updated_at, version on a freshly created mutable resource."""
    now = clock.now_iso()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    return record


def stamp_update(record):
    """Refresh updated_at and bump version (atomic per resource)."""
    record["updated_at"] = clock.now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def stamp_immutable(record):
    """Set created_at on append-only resource (no updated_at/version)."""
    record["created_at"] = clock.now_iso()
    return record


def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_INPUT, "JSON body must be an object")
    return body


def require_field(body, field, etype=None):
    if field not in body:
        raise_error(ERR_INVALID_INPUT, f"missing required field {field}")
    val = body[field]
    if val is None:
        raise_error(ERR_INVALID_INPUT, f"field {field} cannot be null")
    if etype is not None and not isinstance(val, etype):
        raise_error(ERR_INVALID_INPUT, f"field {field} has wrong type")
    return val


def sort_by_created_at(items):
    return sorted(items, key=lambda x: x.get("created_at", ""))
