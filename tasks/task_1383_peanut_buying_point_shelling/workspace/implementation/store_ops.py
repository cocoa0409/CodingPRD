"""Shared request/entity helpers: body validation, path resolution, pagination."""
import uuid
from decimal import Decimal, InvalidOperation

from flask import request

from db import store
from errors import not_found, invalid_request
from timeutil import parse_datetime

MAX_DECIMAL_PLACES_3 = Decimal("0.001")
MAX_DECIMAL_PLACES_2 = Decimal("0.01")


def new_id():
    return str(uuid.uuid4())


def new_common_fields():
    return {
        "id": new_id(),
        "created_at": store.clock,
        "updated_at": store.clock,
        "version": 1,
        "_seq": next(store.seq),
    }


def new_junction_fields():
    """AllocationLine carries only id + created_at (PRD 2.4 exception)."""
    return {"id": new_id(), "created_at": store.clock, "_seq": next(store.seq)}


def touch(entity):
    """Every mutation refreshes updated_at and increments version (PRD 2.4/2.8)."""
    entity["version"] += 1
    entity["updated_at"] = store.clock


def get_or_404(collection, entity_id):
    ent = collection.get(entity_id)
    if ent is None:
        raise not_found()
    return ent


def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise invalid_request("Missing required field: %s" % name)
    return data[name]


def req_str(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, str):
        raise invalid_request("Field %s must be a string" % name)
    return v


def req_int(data, name, minimum=None):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request("Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise invalid_request("Field %s must be >= %d" % (name, minimum))
    return v


def req_bool(data, name):
    v = req_field(data, name)
    if not isinstance(v, bool):
        raise invalid_request("Field %s must be a boolean" % name)
    return v


def req_enum(data, name, allowed):
    v = req_field(data, name)
    if v not in allowed:
        raise invalid_request("Field %s must be one of %s" % (name, ", ".join(allowed)))
    return v


def to_decimal(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise invalid_request("Field %s must be a number" % name)
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise invalid_request("Field %s must be a number" % name)
    if not d.is_finite():
        raise invalid_request("Field %s must be a finite number" % name)
    return d


def _check_dp(d, max_dp, name):
    if -d.as_tuple().exponent > max_dp:
        raise invalid_request("Field %s carries more than %d decimal places" % (name, max_dp))


def req_tons(data, name, minimum_exclusive=True, allow_zero=False):
    """Tonnage: number, > 0 (or >= 0 when allow_zero), at most 3 decimal places."""
    d = to_decimal(req_field(data, name), name)
    _check_dp(d, 3, name)
    if allow_zero:
        if d < 0:
            raise invalid_request("Field %s must be >= 0" % name)
    elif d <= 0:
        raise invalid_request("Field %s must be > 0" % name)
    return d


def req_pct(data, name):
    """Percentage: number in [0, 100], at most 2 decimal places (PRD 2.6)."""
    d = to_decimal(req_field(data, name), name)
    _check_dp(d, 2, name)
    if d < 0 or d > 100:
        raise invalid_request("Field %s must lie between 0 and 100" % name)
    return d


def req_ppb(data, name):
    """Aflatoxin result: number >= 0, at most 2 decimal places (PRD 2.6)."""
    d = to_decimal(req_field(data, name), name)
    _check_dp(d, 2, name)
    if d < 0:
        raise invalid_request("Field %s must be >= 0" % name)
    return d


def req_datetime(data, name):
    v = req_field(data, name)
    try:
        return parse_datetime(v)
    except ValueError:
        raise invalid_request("Field %s must be an ISO 8601 datetime" % name)


def paginate(items):
    """PRD 2.3: limit (default 10, min 1, max 100), offset (default 0).
    Items are pre-sorted by creation (insertion sequence) ascending."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, pagination


def sorted_by_creation(items):
    return sorted(items, key=lambda e: e["_seq"])


def list_response(items, serializer):
    page, pagination = paginate(sorted_by_creation(items))
    from respond import success
    return success([serializer(e) for e in page], response_type="array", pagination=pagination)
