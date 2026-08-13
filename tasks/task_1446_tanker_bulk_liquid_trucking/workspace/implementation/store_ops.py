"""Shared request/entity helpers: body validation, path resolution,
pagination, common system fields."""
import uuid
from datetime import date

from flask import request

from db import store
from errors import invalid_request, not_found_for
from timeutil import parse_date_value, parse_datetime_value


def new_id():
    return str(uuid.uuid4())


def new_common_fields():
    """PRD 2.4: id plus created_at/updated_at/version; version starts at 1."""
    return {"created_at": store.clock, "updated_at": store.clock, "version": 1}


def touch(entity):
    """Every mutation refreshes updated_at and increments version (PRD 2.4);
    cascading side effects count as mutations on each affected resource."""
    entity["version"] += 1
    entity["updated_at"] = store.clock


def get_or_404(collection, coll_name, entity_id):
    """Priority 3: existence. Each collection maps to its dedicated 404."""
    ent = collection.get(entity_id) if isinstance(entity_id, str) else None
    if ent is None:
        raise not_found_for(coll_name, entity_id)
    return ent


def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def reject_unknown(data, allowed):
    """Priority 4: unknown body fields are rejected."""
    extra = set(data.keys()) - set(allowed)
    if extra:
        raise invalid_request("Unknown body field(s): %s" % ", ".join(sorted(extra)))


def req_field(data, name):
    if name not in data or data[name] is None:
        raise invalid_request("Missing required field: %s" % name)
    return data[name]


def req_str(data, name):
    v = req_field(data, name)
    if not isinstance(v, str) or isinstance(v, bool):
        raise invalid_request("Field %s must be a string" % name)
    return v


def opt_str(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_str(data, name)


def req_int(data, name, minimum=None):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request("Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise invalid_request("Field %s must be >= %d" % (name, minimum))
    return v


def opt_int(data, name, default=None, minimum=None):
    if name not in data or data[name] is None:
        return default
    return req_int(data, name, minimum=minimum)


def req_number(data, name, minimum=None, exclusive_minimum=False):
    """JSON number (int or float, not bool). Returned as given."""
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request("Field %s must be a number" % name)
    if minimum is not None:
        if exclusive_minimum and not v > minimum:
            raise invalid_request("Field %s must be > %s" % (name, minimum))
        if not exclusive_minimum and v < minimum:
            raise invalid_request("Field %s must be >= %s" % (name, minimum))
    return v


def req_bool(data, name):
    v = req_field(data, name)
    if not isinstance(v, bool):
        raise invalid_request("Field %s must be a boolean" % name)
    return v


def opt_bool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    return req_bool(data, name)


def req_enum(data, name, allowed):
    v = req_field(data, name)
    if not isinstance(v, str) or v not in allowed:
        raise invalid_request("Field %s must be one of %s" % (name, ", ".join(allowed)))
    return v


def opt_enum(data, name, allowed, default=None):
    if name not in data or data[name] is None:
        return default
    return req_enum(data, name, allowed)


def req_enum_list(data, name, allowed):
    v = req_field(data, name)
    if not isinstance(v, list):
        raise invalid_request("Field %s must be an array" % name)
    for item in v:
        if not isinstance(item, str) or item not in allowed:
            raise invalid_request(
                "Field %s entries must be one of %s" % (name, ", ".join(allowed)))
    return v


def req_str_list(data, name):
    v = req_field(data, name)
    if not isinstance(v, list):
        raise invalid_request("Field %s must be an array" % name)
    for item in v:
        if not isinstance(item, str):
            raise invalid_request("Field %s entries must be strings" % name)
    return v


def req_datetime(data, name):
    v = req_field(data, name)
    try:
        return parse_datetime_value(v)
    except ValueError:
        raise invalid_request("Field %s must be an ISO 8601 datetime" % name)


def req_date(data, name):
    v = req_field(data, name)
    try:
        return parse_date_value(v)
    except ValueError:
        raise invalid_request("Field %s must be an ISO date (YYYY-MM-DD)" % name)


def paginate(items):
    """PRD 2.3: limit (default 10, min 1, max 100), offset (default 0).
    Items arrive pre-sorted by created_at ascending (insertion sequence)."""
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
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, pagination


def sorted_by_creation(items):
    return sorted(items, key=lambda e: e["_seq"])
