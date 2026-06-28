"""Shared helpers: validation primitives, pagination, money rounding, time."""

import math
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from flask import request

from db import db, iso_now, new_id
from errors import err


# --------------------------------------------------------------------------
# Money / rounding (PRD 2.5) — round-half-up to whole cents.
# --------------------------------------------------------------------------
def round_half_up_cents(value):
    """Round a numeric value (cents) to the nearest whole cent, half rounds up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round a numeric value to two decimal places, half rounds up (PRD 2.5:
    net_area_sqft and billable_area_sqft carry two decimals)."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Time parsing
# --------------------------------------------------------------------------
def parse_iso8601(s):
    """Parse an ISO 8601 instant (trailing Z accepted) to an aware UTC datetime.
    Returns None on failure."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_format(dt):
    """Render an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_months(dt, months):
    """Add a whole number of months to an aware datetime (calendar arithmetic)."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp day to the last valid day of the target month.
    import calendar

    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


# --------------------------------------------------------------------------
# Body parsing
# --------------------------------------------------------------------------
def get_json_body():
    """Return the request JSON object, or {} when no body. Raise
    ERR_INVALID_REQUEST when the body is present but not a JSON object."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


# --------------------------------------------------------------------------
# Pagination (PRD 2.3) — limit default 10, min 1, max 100; offset default 0,
# min 0. Out of bounds -> ERR_VALIDATION_PAGINATION.
# --------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION_PAGINATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION_PAGINATION", "limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION_PAGINATION", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_VALIDATION_PAGINATION", "offset must be >= 0.")

    return limit, offset


def paginate(items, serialize):
    """Sort by created_at ASC (creation order via _seq), apply limit/offset,
    build the pagination meta block. `items` is the full filtered raw list."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: r["_seq"])
    total = len(ordered)
    window = ordered[offset : offset + limit]
    data = [serialize(r) for r in window]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return data, pagination


# --------------------------------------------------------------------------
# System field management
# --------------------------------------------------------------------------
def stamp_new(record):
    """Attach full system fields (id, created_at, updated_at, version, _seq) to a
    freshly created record carrying the common-fields trio."""
    now = iso_now()
    record["id"] = record.get("id") or new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def stamp_new_minimal(record):
    """Attach only id + created_at + _seq (no updated_at, no version) for
    TurfProduct, InfillProduct, and Payment (PRD 2.4 exceptions)."""
    record["id"] = record.get("id") or new_id()
    record["created_at"] = iso_now()
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Refresh updated_at and increment version on a mutation (incl. cascades)."""
    record["updated_at"] = iso_now()
    record["version"] = record["version"] + 1


# --------------------------------------------------------------------------
# Validation primitives (priority 6: ERR_INVALID_REQUEST)
# --------------------------------------------------------------------------
def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}.")


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string.")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} has an invalid value.")
    return v


def require_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a number.")
    return v


def require_number_gt(body, field, threshold):
    v = require_number(body, field)
    if not (v > threshold):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be > {threshold}.")
    return v


def require_number_ge(body, field, threshold):
    v = require_number(body, field)
    if not (v >= threshold):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {threshold}.")
    return v


def require_int_gt(body, field, threshold):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    if not (v > threshold):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be > {threshold}.")
    return v


def require_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean.")
    return v


def optional_number_ge(body, field, threshold, default):
    if field not in body or body[field] is None:
        return default
    return require_number_ge(body, field, threshold)


# --------------------------------------------------------------------------
# Serialization — strip internal-only keys (those prefixed with "_").
# --------------------------------------------------------------------------
def public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}
