"""Shared request-parsing helpers for routes."""
from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import raise_err


def body():
    if not request.is_json:
        raise_err("ERR_INVALID_REQUEST", "Request body must be JSON")
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise_err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    return data[name]


def opt_field(data, name, default=None):
    v = data.get(name, default)
    return v


def as_str(v, name):
    if not isinstance(v, str):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    return v


def as_decimal(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a number")
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a number")


def as_dt(v, name):
    if not isinstance(v, str):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an ISO8601 string")
    try:
        return db._parse_iso(v)
    except Exception:
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a valid ISO8601 datetime")


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(allowed)}")
    return v


def pagination_args():
    """Parse limit/offset per response_envelope.pagination_defaults (10 / min 1 / max 100 / offset 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except ValueError:
            raise_err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except ValueError:
            raise_err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise_err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def sorted_page(items, limit, offset):
    """Sort by created_at ASC then slice."""
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
