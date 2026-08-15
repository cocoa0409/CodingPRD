"""Shared request-validation helpers."""

from flask import request

import db
from errors import fail


def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        fail("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    return body[name]


def require_str(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    return v


def opt_str(body, name):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not isinstance(v, str) or isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    return v


def require_int(body, name, minimum=None, maximum=None):
    v = require_field(body, name)
    if not isinstance(v, int) or isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", f"Field {name} below minimum {minimum}")
    if maximum is not None and v > maximum:
        fail("ERR_INVALID_REQUEST", f"Field {name} above maximum {maximum}")
    return v


def opt_int(body, name, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not isinstance(v, int) or isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", f"Field {name} below minimum {minimum}")
    if maximum is not None and v > maximum:
        fail("ERR_INVALID_REQUEST", f"Field {name} above maximum {maximum}")
    return v


def require_bool(body, name):
    v = require_field(body, name)
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return v


def require_enum(body, name, allowed):
    v = require_str(body, name)
    if v not in allowed:
        fail("ERR_INVALID_REQUEST", f"Field {name} has unknown value {v}")
    return v


def require_list(body, name):
    v = require_field(body, name)
    if not isinstance(v, list):
        fail("ERR_INVALID_REQUEST", f"Field {name} must be an array")
    return v


def parse_dt(body, name):
    v = require_str(body, name)
    try:
        return db._parse_iso(v)
    except Exception:
        fail("ERR_INVALID_REQUEST", f"Field {name} is not a valid ISO-8601 instant")


def opt_parse_dt(body, name):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", f"Field {name} must be an ISO-8601 string")
    try:
        return db._parse_iso(v)
    except Exception:
        fail("ERR_INVALID_REQUEST", f"Field {name} is not a valid ISO-8601 instant")


def paginate(items):
    """Parse limit/offset from query args with scaffold defaults and bounds."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit out of range [1, 100]")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    total = len(items)
    return limit, offset, total, items[offset:offset + limit]


def sort_by_created(records):
    return sorted(records, key=lambda r: (r.get("created_at", ""), r.get("id", "")))


def get_or_404(store, rid):
    if not isinstance(rid, str) or rid not in store:
        fail("ERR_NOT_FOUND", "Resource not found")
    return store[rid]
