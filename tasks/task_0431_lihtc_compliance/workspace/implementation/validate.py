"""Body parsing, field type/enum validation, and pagination helpers."""

from flask import request

import errors


def get_json_body():
    """Return the parsed JSON body as a dict; {} when empty. Malformed -> ERR_VALIDATION."""
    if request.content_length in (None, 0) and not (request.data or b"").strip():
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.validation("Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.validation("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.validation(f"Missing required field: {f}")


def as_str(body, key, required=True):
    if key not in body or body[key] is None:
        if required:
            raise errors.validation(f"Missing required field: {key}")
        return None
    v = body[key]
    if not isinstance(v, str) or v == "":
        raise errors.validation(f"Field {key} must be a non-empty string")
    return v


def as_int(body, key, required=True, default=None, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        if required:
            raise errors.validation(f"Missing required field: {key}")
        return default
    v = body[key]
    # bool is a subclass of int — reject it as an integer field
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"Field {key} must be an integer")
    if minimum is not None and v < minimum:
        raise errors.validation(f"Field {key} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise errors.validation(f"Field {key} must be <= {maximum}")
    return v


def as_bool(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise errors.validation(f"Missing required field: {key}")
        return default
    v = body[key]
    if not isinstance(v, bool):
        raise errors.validation(f"Field {key} must be a boolean")
    return v


def as_enum(body, key, allowed, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise errors.validation(f"Missing required field: {key}")
        return default
    v = body[key]
    if v not in allowed:
        raise errors.validation(f"Field {key} must be one of {sorted(allowed)}")
    return v


def as_datetime(body, key, required=True, default=None):
    """Require a string datetime; we keep the raw value (no normalization for stored input)."""
    if key not in body or body[key] is None:
        if required:
            raise errors.validation(f"Missing required field: {key}")
        return default
    v = body[key]
    if not isinstance(v, str) or v == "":
        raise errors.validation(f"Field {key} must be an ISO 8601 datetime string")
    return v


def as_int_array(body, key, required=True, default=None, length=None):
    if key not in body or body[key] is None:
        if required:
            raise errors.validation(f"Missing required field: {key}")
        return default
    v = body[key]
    if not isinstance(v, list):
        raise errors.validation(f"Field {key} must be an array")
    for item in v:
        if isinstance(item, bool) or not isinstance(item, int):
            raise errors.validation(f"Field {key} must be an array of integers")
    if length is not None and len(v) != length:
        raise errors.validation(f"Field {key} must have exactly {length} elements")
    return v


def parse_pagination():
    """Parse limit/offset query params with defaults limit=10 (1..100), offset=0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.validation("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.validation("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """Return (page, pagination_meta). items must be pre-sorted."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta
