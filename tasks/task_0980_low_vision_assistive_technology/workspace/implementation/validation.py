"""Shared request-body validation helpers (priority 3: ERR_VALIDATION)."""

import errors
from db import parse_datetime


def require_body(body):
    if body is None or not isinstance(body, dict):
        raise errors.validation("Request body must be a JSON object")
    return body


def req_string(body, field):
    if field not in body:
        raise errors.validation(f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, str) or not v:
        raise errors.validation(f"Field {field} must be a non-empty string")
    return v


def opt_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise errors.validation(f"Field {field} must be a string")
    return v


def req_int(body, field, min_v=None, max_v=None):
    if field not in body:
        raise errors.validation(f"Missing required field: {field}")
    return _int_value(body[field], field, min_v, max_v)


def opt_int(body, field, default=None, min_v=None, max_v=None):
    if field not in body or body[field] is None:
        return default
    return _int_value(body[field], field, min_v, max_v)


def _int_value(v, field, min_v, max_v):
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"Field {field} must be an integer")
    if min_v is not None and v < min_v:
        raise errors.validation(f"Field {field} out of range")
    if max_v is not None and v > max_v:
        raise errors.validation(f"Field {field} out of range")
    return v


def req_enum(body, field, allowed):
    v = req_string(body, field)
    if v not in allowed:
        raise errors.validation(f"Field {field} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, allowed)


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise errors.validation(f"Field {field} must be a boolean")
    return v


def req_datetime(body, field):
    v = req_string(body, field)
    try:
        return parse_datetime(v)
    except ValueError:
        raise errors.validation(f"Field {field} is a malformed datetime")


def opt_datetime(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return req_datetime(body, field)


def reject_unknown_fields(body, allowed_fields):
    for k in body.keys():
        if k not in allowed_fields:
            raise errors.validation(f"Unknown field: {k}")


def parse_pagination(args):
    """limit/offset per envelope defaults: limit default 10, min 1, max 100; offset default 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.validation("limit out of range (1..100)")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.validation("offset must be an integer")
        if offset < 0:
            raise errors.validation("offset must be >= 0")
    return limit, offset


def apply_filters(items, filters):
    """filters: list of (query_value, entity_field). None query values are skipped."""
    out = []
    for item in items:
        ok = True
        for qv, field in filters:
            if qv is not None and item.get(field) != qv:
                ok = False
                break
        if ok:
            out.append(item)
    return out


def sort_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["id"]))
