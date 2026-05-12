"""Shared helpers: OCC checks, version bumping, pagination, body parsing."""

from datetime import timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from clock import CLOCK
from errors import (
    not_found,
    stale_version,
    validation_error,
)


def get_json_body() -> dict:
    if not request.is_json and not (request.data and request.content_type and "json" in request.content_type):
        if not request.data:
            return {}
    try:
        body = request.get_json(silent=True, force=True)
    except Exception:
        raise validation_error("Invalid JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise validation_error("Request body must be a JSON object")
    return body


def bump_version(record):
    record["version"] = int(record.get("version", 0)) + 1
    record["updated_at"] = CLOCK.now()
    return record


def stamp_create(record):
    now = CLOCK.now()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    return record


def stamp_create_appendonly(record):
    record["created_at"] = CLOCK.now()
    return record


def check_occ(record, body, field="version"):
    """OCC: if request body includes version (non-null), it must match."""
    if field in body and body[field] is not None:
        try:
            supplied = int(body[field])
        except (TypeError, ValueError):
            raise stale_version("version field must be an integer")
        if supplied != int(record.get(field, 0)):
            raise stale_version()


def parse_pagination():
    """Read limit/offset query parameters per scaffold defaults: limit=10 (1..100), offset=0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise validation_error("limit must be an integer")
        if limit < 1 or limit > 100:
            raise validation_error("limit out of range (1..100)")
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise validation_error("offset must be an integer")
        if offset < 0:
            raise validation_error("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset : offset + limit]
    has_more = (offset + len(page)) < total
    return page, total, has_more


def require_str(body, key, *, optional=False, allow_empty=False):
    if key not in body or body[key] is None:
        if optional:
            return None
        raise validation_error(f"{key} is required")
    val = body[key]
    if not isinstance(val, str):
        raise validation_error(f"{key} must be a string")
    if not allow_empty and not val.strip():
        raise validation_error(f"{key} must be non-empty")
    return val


def require_number(body, key, *, optional=False):
    if key not in body or body[key] is None:
        if optional:
            return None
        raise validation_error(f"{key} is required")
    val = body[key]
    if isinstance(val, bool):
        raise validation_error(f"{key} must be a number")
    if not isinstance(val, (int, float)):
        raise validation_error(f"{key} must be a number")
    return float(val)


def require_int(body, key, *, optional=False):
    if key not in body or body[key] is None:
        if optional:
            return None
        val = body[key]
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise validation_error(f"{key} must be an integer")
    return val


def to_aware_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fetch_or_404(table, key):
    rec = table.get(key)
    if rec is None:
        raise not_found()
    return rec


def round_half_up_2(value) -> float:
    """Round a numeric value to 2 decimal places using HALF_UP."""
    if value is None:
        return 0.0
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def round_half_up_1(value) -> float:
    if value is None:
        return 0.0
    d = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(d)


def round_half_up_int(value) -> int:
    if value is None:
        return 0
    d = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)
