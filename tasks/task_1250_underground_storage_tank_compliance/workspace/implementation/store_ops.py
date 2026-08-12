"""Shared request/entity helpers: closed-schema body validation, path
resolution, pagination, common system fields."""
import uuid

from flask import request

from db import store
from errors import invalid_request
from timeutil import parse_instant, parse_period


def new_id():
    return str(uuid.uuid4())


def new_common_fields():
    return {"created_at": store.clock, "updated_at": store.clock, "version": 1}


def touch(entity):
    """Every mutation refreshes updated_at and increments version (PRD 2.5/2.6),
    including mutations driven by system cascades."""
    entity["version"] += 1
    entity["updated_at"] = store.clock


def get_or_404(collection, entity_id, not_found_fn):
    ent = collection.get(entity_id)
    if ent is None:
        raise not_found_fn()
    return ent


def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def check_closed(data, allowed):
    """Payload keys are closed under the endpoint's declared input schema."""
    extra = [k for k in data.keys() if k not in allowed]
    if extra:
        raise invalid_request("Unexpected field(s): %s" % ", ".join(sorted(extra)))


def req_field(data, name):
    if name not in data or data[name] is None:
        raise invalid_request("Missing required field: %s" % name)
    return data[name]


def req_str(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, str):
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


def opt_int(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_int(data, name)


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
    if v not in allowed:
        raise invalid_request("Field %s must be one of %s" % (name, ", ".join(allowed)))
    return v


def opt_enum(data, name, allowed, default=None):
    if name not in data or data[name] is None:
        return default
    return req_enum(data, name, allowed)


def req_number(data, name):
    """A JSON number (int or float), excluding booleans."""
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request("Field %s must be a number" % name)
    return v


def req_instant(data, name):
    v = req_field(data, name)
    try:
        return parse_instant(v)
    except ValueError:
        raise invalid_request("Field %s must be an ISO 8601 datetime" % name)


def opt_instant(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_instant(data, name)


def req_period(data, name):
    v = req_field(data, name)
    try:
        parse_period(v)
    except ValueError:
        raise invalid_request("Field %s must be a YYYY-MM month" % name)
    return v


def req_list(data, name):
    v = req_field(data, name)
    if not isinstance(v, list):
        raise invalid_request("Field %s must be an array" % name)
    return v


def opt_version(data, name):
    """OCC expected_*_version: accept an integer or a decimal string."""
    v = req_field(data, name)
    if isinstance(v, bool):
        raise invalid_request("Field %s must be an integer" % name)
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.isdigit():
        return int(v)
    raise invalid_request("Field %s must be an integer" % name)


def sorted_by_creation(items):
    return sorted(items, key=lambda e: e["_seq"])


def paginate(items):
    """PRD 2.3: limit (default 10, min 1, max 100), offset (default 0).
    Callers pass items pre-sorted by creation ascending."""
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


def qparam(name):
    return request.args.get(name)


def qparam_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    raise invalid_request("Query parameter %s must be true or false" % name)
