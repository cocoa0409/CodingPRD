"""Shared parsing / validation / serialization helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError

# Pagination defaults (scaffold §1.0 pagination_defaults).
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def get_json_body():
    """Return the parsed JSON object, or {} when absent. Malformed -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def parse_utc(value, field="datetime"):
    """Parse an ISO 8601 instant into an aware UTC datetime. Raises ERR_INVALID_REQUEST."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 string." % field)
    raw = value.strip()
    s = raw
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Field %s is not a valid ISO 8601 instant." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso_millis(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def require_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (field, minimum))
    return v


def require_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a number." % field)
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return v


def optional_number(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a number." % field)
    return v


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    return v


def optional_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a string." % field)
    return v


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a non-empty string." % field)
    return v


def pagination_params():
    """Parse limit/offset from query string per scaffold defaults."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN:
            limit = PAGE_LIMIT_MIN
        elif limit > PAGE_LIMIT_MAX:
            limit = PAGE_LIMIT_MAX
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """items: list already sorted by created_at ASC. Returns (page, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def round_half_up_cents(amount):
    """Round a Decimal/number to whole cents, ROUND_HALF_UP, return int."""
    d = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def hours_between(start_dt, end_dt):
    """Exact (unrounded) hours between two aware datetimes."""
    return (end_dt - start_dt).total_seconds() / 3600.0


def sort_by_created(records):
    """Sort by created_at ASC, tie-broken by internal creation sequence."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
