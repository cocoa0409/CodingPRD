"""Shared request-parsing / validation helpers."""
from datetime import datetime, timezone

from flask import request

import errors


def get_body():
    """Return the JSON body as a dict, or raise ERR_INVALID_REQUEST if it is not
    a JSON object."""
    if request.method in ("GET",):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # No body provided: treat as empty for action endpoints that take no input.
        if request.data and request.data.strip():
            raise errors.invalid_request("Malformed JSON body")
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.invalid_request(f"Missing required field: {f}")


def as_str(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {key}")
        return default
    val = body[key]
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field {key} must be a string")
    return val


def as_int(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {key}")
        return default
    val = body[key]
    # bool is a subclass of int; reject it as a non-integer for numeric fields.
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {key} must be an integer")
    return val


def as_number(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {key}")
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field {key} must be a number")
    return val


def as_bool(body, key, required=False, default=False):
    if key not in body or body[key] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {key}")
        return default
    val = body[key]
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field {key} must be a boolean")
    return val


def as_enum(body, key, allowed, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {key}")
        return default
    val = body[key]
    if val not in allowed:
        raise errors.invalid_request(
            f"Field {key} must be one of {sorted(allowed)}")
    return val


def as_datetime(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {key}")
        return default
    val = body[key]
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field {key} must be an ISO 8601 string")
    return parse_iso(val, key)


def parse_iso(val, key="timestamp"):
    s = val
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, AttributeError):
        raise errors.invalid_request(f"Field {key} must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def two_upper_letters(val):
    return isinstance(val, str) and len(val) == 2 and val.isalpha() and val.isupper()


# ---- Pagination (PRD §2.3) ----

def pagination_params():
    """limit defaults 10 (min 1, max 100), offset defaults 0 (min 0).
    Over-max limit is capped at 100; invalid values -> ERR_INVALID_REQUEST."""
    limit = _parse_pos_int_qs("limit", 10)
    offset = _parse_pos_int_qs("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_pos_int_qs(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise errors.invalid_request(f"Query parameter {name} must be an integer")


def paginate(items, limit, offset):
    """items must already be sorted. Returns (window, total_count, has_more)."""
    total = len(items)
    window = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return window, total, has_more


def sort_by_created(items):
    """Sort by created_at ascending, breaking ties by the internal creation seq."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
