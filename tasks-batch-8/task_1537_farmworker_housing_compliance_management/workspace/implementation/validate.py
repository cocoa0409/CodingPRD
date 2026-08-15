"""Shared body-shape validation, pagination, and lookup helpers."""

from flask import request

from errors import err
import db


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def req_field(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    return body[name]


def opt_field(body, name, default=None):
    v = body.get(name, default)
    return v


def require_string(body, name):
    v = req_field(body, name)
    if not isinstance(v, str) or isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    return v


def require_int(body, name, min_value=None):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if min_value is not None and v < min_value:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be >= {min_value}")
    return v


def require_number(body, name):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a number")
    return v


def require_bool(body, name):
    v = req_field(body, name)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return v


def require_enum(body, name, allowed):
    v = req_field(body, name)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(allowed)}")
    return v


def optional_enum(body, name, allowed):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(allowed)}")
    return v


def optional_string(body, name):
    if name not in body:
        return None
    v = body[name]
    if v is not None and not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    return v


def optional_int(body, name, min_value=None):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if min_value is not None and v < min_value:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be >= {min_value}")
    return v


def parse_date_strict(value, field_name):
    import clock
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field_name} must be an ISO 8601 date string")
    try:
        return clock.parse_date(value)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"Field {field_name} must be a valid ISO 8601 date (YYYY-MM-DD)")


def parse_pagination():
    """limit (default 10, min 1, max 100), offset (default 0)."""
    args = request.args
    limit_raw = args.get("limit", "10")
    offset_raw = args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(offset_raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def get_filter(name):
    return request.args.get(name)


def sort_and_paginate(items, limit, offset):
    # Sort by created_at ascending (PRD §2.3). Python's sort is stable, so
    # millisecond ties keep store insertion (= creation) order rather than a
    # random UUID tiebreak — this keeps "X posted after Y" observable.
    items = sorted(items, key=lambda r: r.get("created_at", ""))
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
