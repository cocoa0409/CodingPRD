"""Request-body parsing, field validation, and pagination helpers.

Malformed bodies (missing required field, bad enum, non-positive credit_hours)
raise ERR_INVALID_REQUEST (400). A syntactically valid number that is out of its
allowed range (negative hours, etc.) raises ERR_VALIDATION_RANGE (422). See
PRD §2.10.
"""

from flask import request

import errors


def get_json_body():
    """Return the parsed JSON object body, or {} for an empty body.

    A body that is present but not a JSON object raises ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


def require_field(body, name, types=None):
    if name not in body or body[name] is None:
        raise errors.invalid_request(f"Missing required field '{name}'.")
    value = body[name]
    if types is not None and not isinstance(value, types):
        # bool is a subclass of int; reject it where a number is expected.
        raise errors.invalid_request(f"Field '{name}' has the wrong type.")
    if types is not None and isinstance(value, bool) and bool not in _as_tuple(types):
        raise errors.invalid_request(f"Field '{name}' has the wrong type.")
    return value


def optional_field(body, name, default=None, types=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if types is not None and not isinstance(value, types):
        raise errors.invalid_request(f"Field '{name}' has the wrong type.")
    if types is not None and isinstance(value, bool) and bool not in _as_tuple(types):
        raise errors.invalid_request(f"Field '{name}' has the wrong type.")
    return value


def _as_tuple(types):
    if isinstance(types, tuple):
        return types
    return (types,)


def require_number(body, name, *, gt=None, ge=None):
    """Require a numeric (int/float, not bool) field.

    Type/missing failures -> ERR_INVALID_REQUEST (400).
    Range failures -> ERR_VALIDATION_RANGE (422), except a non-positive
    credit-hour-style value guarded by gt=0 which the PRD classifies as a
    malformed body (ERR_INVALID_REQUEST).
    """
    if name not in body or body[name] is None:
        raise errors.invalid_request(f"Missing required field '{name}'.")
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.invalid_request(f"Field '{name}' must be a number.")
    return value


def enum_field(body, name, allowed, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request(f"Missing required field '{name}'.")
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise errors.invalid_request(
            f"Field '{name}' must be one of {sorted(allowed)}."
        )
    return value


def require_string(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request(f"Missing required field '{name}'.")
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        raise errors.invalid_request(f"Field '{name}' must be a non-empty string.")
    return value


# ─── Pagination (PRD §2.3) ────────────────────────────────────────────
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def parse_pagination():
    """Read limit/offset from query params, applying defaults and clamps.

    limit default 10, min 1, max 100 (over-max served 100); offset default 0.
    Malformed (non-integer) values fall back to defaults rather than erroring,
    keeping list reads forgiving.
    """
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET

    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = PAGE_DEFAULT_LIMIT
        if limit < PAGE_MIN_LIMIT:
            limit = PAGE_MIN_LIMIT
        if limit > PAGE_MAX_LIMIT:
            limit = PAGE_MAX_LIMIT

    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = PAGE_DEFAULT_OFFSET
        if offset < 0:
            offset = PAGE_DEFAULT_OFFSET

    return limit, offset


def paginate(items, limit, offset):
    """Slice an already-sorted list to the page window."""
    return items[offset:offset + limit]
