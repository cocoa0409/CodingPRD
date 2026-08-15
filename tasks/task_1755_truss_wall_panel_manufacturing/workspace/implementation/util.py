"""Shared helpers: decimals, datetimes, request validation, pagination."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND

# ---------------------------------------------------------------------------
# Decimal / numeric helpers (board feet are 2dp half-up; money is integer cents)
# ---------------------------------------------------------------------------

D0 = Decimal("0")
D2 = Decimal("0.01")


def dec(value):
    """Coerce a JSON number to Decimal (via str to avoid binary artifacts)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round2(d):
    return d.quantize(D2, rounding=ROUND_HALF_UP)


def round_cents(d):
    """Round half-up to whole integer cents."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def out_num(d):
    """Serialize a Decimal as int when integral, else float."""
    if d is None:
        return None
    if not isinstance(d, Decimal):
        return d
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Datetime parsing / formatting
# ---------------------------------------------------------------------------

def parse_dt(value, field):
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be an ISO 8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Domain datetimes: second precision when whole, else 3 fractional digits."""
    if dt is None:
        return None
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ts(dt):
    """System timestamps (created_at/updated_at/meta): always 3 fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Request body access and field validators (schema layer -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "request body must be a JSON object")
    return data


def req_present(data, field):
    if field not in data or data[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"missing required field: {field}")
    return data[field]


def as_str(value, field, required=False, default=None):
    if value is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"missing required field: {field}")
        return default
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be a string")
    return value


def as_bool(value, field, required=False, default=None):
    if value is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"missing required field: {field}")
        return default
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be a boolean")
    return value


def as_int(value, field, required=False, default=None):
    if value is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"missing required field: {field}")
        return default
    if isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be an integer")


def as_num(value, field, required=False, default=None):
    """JSON number -> Decimal."""
    if value is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"missing required field: {field}")
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be a number")
    return dec(value)


def as_enum(value, field, allowed, required=False, default=None):
    if value is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"missing required field: {field}")
        return default
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be one of {sorted(allowed)}")
    return value


def as_dt(value, field, required=False, default=None):
    if value is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"missing required field: {field}")
        return default
    return parse_dt(value, field)


def as_fk(value, field, collection, what):
    """Body foreign-key existence (ERR_NOT_FOUND) — used at the existence layer."""
    if value is None:
        return None
    if not isinstance(value, str) or value not in collection:
        raise ApiError(ERR_NOT_FOUND, 404, f"{what} referenced by {field} not found")
    return collection[value]


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3: limit default 10 min 1 max 100; offset default 0)
# ---------------------------------------------------------------------------

def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(records):
    """Records sorted by creation order (created_at ASC == _seq ASC)."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    page = [r for r in page]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def match_filter(record, field, raw):
    """Exact-match list filter. Datetimes compare by canonical serialized form."""
    value = record.get(field)
    if isinstance(value, datetime):
        return fmt_dt(value) == raw
    if isinstance(value, bool):
        return (raw.lower() == "true" and value) or (raw.lower() == "false" and not value)
    if isinstance(value, Decimal):
        return str(out_num(value)) == raw
    return str(value) == raw
