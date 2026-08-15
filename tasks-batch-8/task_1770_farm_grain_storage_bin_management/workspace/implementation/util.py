"""Parsing, validation, rounding, FK resolution, and pagination helpers.

All request-shape failures raise ERR_VALIDATION (400); FK/path resolution
failures raise ERR_NOT_FOUND (404). Bushel quantities quantize to 2dp,
moistures/temperatures to 1dp, half-up (PRD 2.6).
"""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from clock import parse_iso
from errors import ApiError

D1 = Decimal("0.1")
D2 = Decimal("0.01")


def q1(v):
    return Decimal(v).quantize(D1, rounding=ROUND_HALF_UP)


def q2(v):
    return Decimal(v).quantize(D2, rounding=ROUND_HALF_UP)


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError("ERR_VALIDATION", 400, "Request body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
        return data
    return {}


def present(data, field):
    return field in data and data[field] is not None


def required(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {field}")
    return data[field]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def as_str(v, field):
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a string")
    return v


def as_int(v, field):
    if not _is_int(v):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a boolean")
    return v


def as_decimal(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a number")
    try:
        return Decimal(str(v))
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a number")


def as_bu(v, field):
    """Bushel quantity: numeric, stored at exactly 2dp half-up."""
    return q2(as_decimal(v, field))


def as_moisture(v, field):
    """Moisture percent: 1dp, 0..40 inclusive."""
    d = q1(as_decimal(v, field))
    if d < 0 or d > 40:
        raise ApiError("ERR_VALIDATION", 400,
                       f"Field {field} must be between 0 and 40 inclusive")
    return d


def as_dt(v, field):
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be an ISO 8601 timestamp")
    try:
        return parse_iso(v)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400,
                       f"Field {field} must be a valid ISO 8601 timestamp")


def as_enum(v, field, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", 400,
                       f"Field {field} must be one of {sorted(allowed)}")
    return v


def resolve_path(collection, value, what="resource"):
    """Path identifier resolution (404)."""
    rec = collection.get(value) if isinstance(value, str) else None
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{what} not found")
    return rec


def resolve_body_fk(collection, data, field, what=None):
    """Body FK resolution at existence priority: when the field is present and
    non-null, it must resolve or ERR_NOT_FOUND. When absent, returns None and
    the shape layer reports the missing field as ERR_VALIDATION."""
    if present(data, field):
        v = data[field]
        rec = collection.get(v) if isinstance(v, str) else None
        if rec is None:
            raise ApiError("ERR_NOT_FOUND", 404,
                           f"{what or field} does not resolve to an existing resource")
        return rec
    return None


def pagination_args():
    """limit/offset per scaffold: default 10/0, limit min 1 max 100, offset >= 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def paginate_sorted(recs):
    """Sort by created_at ascending (insertion order breaks ties) and paginate.

    Returns (page_items, total_count, limit, offset)."""
    limit, offset = pagination_args()
    items = sorted(recs, key=lambda r: (r["created_at"], r["seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return page, total, limit, offset


def query_enum(name, allowed):
    """Optional enum list filter; invalid value -> ERR_VALIDATION."""
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise ApiError("ERR_VALIDATION", 400,
                       f"Query parameter {name} must be one of {sorted(allowed)}")
    return raw


def query_str(name):
    return request.args.get(name)


def query_int_required(name):
    raw = request.args.get(name)
    if raw is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required query parameter: {name}")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, f"Query parameter {name} must be an integer")
