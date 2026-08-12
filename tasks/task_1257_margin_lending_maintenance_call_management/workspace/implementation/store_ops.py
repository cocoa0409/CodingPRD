"""Shared request/entity helpers: body validation, path resolution,
pagination, common-field lifecycle.

Validation order implemented across handlers (PRD 2.10):
  0. ERR_INVALID_REQUEST — malformed body / missing fields / bad enum /
     non-positive amounts or quantities ("rejected outright", before the cascade)
  1. user context  2. role authorization  3. existence (path left-to-right,
     then body references)  4. ownership  [4.5 OCC expected_account_version]
  5. state  6. SoD / PDT gate  7. suitability  8. structural  9. temporal/mark
  10. fiscal
"""
import uuid

from flask import request

from db import store
from errors import invalid_request
from timeutil import parse_date, parse_datetime


def new_id():
    return str(uuid.uuid4())


def stamp_new(entity):
    """Common fields for primary resources (PRD 2.7)."""
    entity["_seq"] = next(store.seq)
    entity["created_at"] = store.clock
    entity["updated_at"] = store.clock
    entity["version"] = 1
    return entity


def stamp_ledger(entity):
    """Ledger-style records carry only id/created_at (PRD 2.7)."""
    entity["_seq"] = next(store.seq)
    entity["created_at"] = store.clock
    return entity


def touch(entity):
    """Every mutation refreshes updated_at and increments version (PRD 2.7)."""
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


def req_str(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, str) or not v.strip():
        raise invalid_request("Field %s must be a non-empty string" % name)
    return v


def opt_str(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
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


def opt_int(data, name, default=None, minimum=None):
    if name not in data or data[name] is None:
        return default
    return req_int(data, name, minimum=minimum)


def req_bool(data, name):
    v = req_field(data, name)
    if not isinstance(v, bool):
        raise invalid_request("Field %s must be a boolean" % name)
    return v


def opt_bool(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_bool(data, name)


def req_enum(data, name, allowed):
    v = req_field(data, name)
    if v not in allowed:
        raise invalid_request("Field %s must be one of %s" % (name, ", ".join(allowed)))
    return v


def req_positive_int(data, name):
    """Amounts/quantities: non-positive -> ERR_INVALID_REQUEST (PRD 2.10)."""
    return req_int(data, name, minimum=1)


def req_clock_instant(data, name):
    v = req_field(data, name)
    try:
        return parse_datetime(v)
    except ValueError:
        raise invalid_request("Field %s must be an ISO 8601 datetime" % name)


def req_iso_date(data, name):
    v = req_field(data, name)
    try:
        return parse_date(v)
    except ValueError:
        raise invalid_request("Field %s must be an ISO 8601 date" % name)


def opt_iso_date(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_iso_date(data, name)


def paginate(items):
    """PRD 2.3: limit (default 10, min 1, max 100), offset (default 0).
    Callers pass items pre-sorted by created_at ascending."""
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
