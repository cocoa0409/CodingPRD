"""Shared request/entity helpers: body validation, path resolution,
pagination, snapshot/restore for atomic multi-step writes."""
import copy
import uuid

from flask import request

from db import store, COLLECTIONS
from errors import invalid_request
from timeutil import parse_temporal, DATE_RE
from datetime import date


def new_id():
    return str(uuid.uuid4())


def new_common_fields():
    return {"created_at": store.clock, "updated_at": store.clock, "version": 1}


def touch(entity):
    """Every mutation refreshes updated_at and increments version (PRD 2.4)."""
    entity["version"] += 1
    entity["updated_at"] = store.clock


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


def opt_field(data, name, default=None):
    v = data.get(name, default)
    return default if v is None else v


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


def req_bool(data, name):
    v = req_field(data, name)
    if not isinstance(v, bool):
        raise invalid_request("Field %s must be a boolean" % name)
    return v


def opt_bool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, bool):
        raise invalid_request("Field %s must be a boolean" % name)
    return v


def req_enum(data, name, allowed):
    v = req_field(data, name)
    if v not in allowed:
        raise invalid_request("Field %s must be one of %s" % (name, ", ".join(allowed)))
    return v


def opt_enum(data, name, allowed, default=None):
    if name not in data or data[name] is None:
        return default
    return req_enum(data, name, allowed)


def req_date(data, name):
    """Parse a YYYY-MM-DD string to datetime.date; raises invalid_request otherwise."""
    v = req_field(data, name)
    if not isinstance(v, str) or not DATE_RE.match(v):
        raise invalid_request("Field %s must be a YYYY-MM-DD date string" % name)
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise invalid_request("Field %s must be a valid YYYY-MM-DD date" % name)


def opt_date(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_date(data, name)


def req_temporal(data, name):
    v = req_field(data, name)
    try:
        return parse_temporal(v)
    except ValueError:
        raise invalid_request("Field %s must be an ISO 8601 date or datetime" % name)


def opt_temporal(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_temporal(data, name)


def opt_str_list(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, list):
        raise invalid_request("Field %s must be an array" % name)
    for item in v:
        if not isinstance(item, str) or isinstance(item, bool):
            raise invalid_request("Field %s members must be strings" % name)
    return v


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


def snapshot_store():
    return {name: copy.deepcopy(getattr(store, name)) for name in COLLECTIONS}


def restore_store(snap):
    for name in COLLECTIONS:
        setattr(store, name, snap[name])
