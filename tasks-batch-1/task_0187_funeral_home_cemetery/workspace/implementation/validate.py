"""Request-body validation helpers (PRD §2.3 pagination, §2.9 ordering).

These produce ERR_INVALID_REQUEST (422) for malformed bodies and
ERR_VALIDATION_OUT_OF_RANGE (422) for pagination bounds.
"""
from flask import request

import errors

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0


def get_json():
    """Return the parsed JSON body as a dict ({} when absent)."""
    if request.method in ("GET", "DELETE"):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def pagination():
    """Parse + bound-check limit/offset query params.

    Out-of-bounds (or non-integer) values -> ERR_VALIDATION_OUT_OF_RANGE (422).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.out_of_range("limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise errors.out_of_range("limit out of range")

    if raw_offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.out_of_range("offset must be an integer")
        if offset < PAGINATION_MIN_OFFSET:
            raise errors.out_of_range("offset out of range")

    return limit, offset


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise errors.invalid_request("Missing required field: %s" % n)


def require_string(body, name):
    require_fields(body, name)
    v = body[name]
    if not isinstance(v, str) or v == "":
        raise errors.invalid_request("Field %s must be a non-empty string" % name)
    return v


def require_enum(body, name, allowed):
    require_fields(body, name)
    v = body[name]
    if v not in allowed:
        raise errors.invalid_request("Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def require_int(body, name, minimum=None, maximum=None):
    require_fields(body, name)
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request("Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise errors.invalid_request("Field %s below minimum %s" % (name, minimum))
    if maximum is not None and v > maximum:
        raise errors.invalid_request("Field %s above maximum %s" % (name, maximum))
    return v


def optional_int(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request("Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise errors.invalid_request("Field %s below minimum %s" % (name, minimum))
    if maximum is not None and v > maximum:
        raise errors.invalid_request("Field %s above maximum %s" % (name, maximum))
    return v


def optional_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise errors.invalid_request("Field %s must be a boolean" % name)
    return v


def require_number(body, name, minimum=None, maximum=None,
                   min_inclusive=True, max_inclusive=True):
    """Numeric (int or float) — used for sales_tax_pct / state_trust_pct fractions."""
    require_fields(body, name)
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_request("Field %s must be a number" % name)
    if minimum is not None:
        if min_inclusive and v < minimum:
            raise errors.invalid_request("Field %s below minimum" % name)
        if not min_inclusive and v <= minimum:
            raise errors.invalid_request("Field %s must be strictly greater than %s" % (name, minimum))
    if maximum is not None:
        if max_inclusive and v > maximum:
            raise errors.invalid_request("Field %s above maximum" % name)
        if not max_inclusive and v >= maximum:
            raise errors.invalid_request("Field %s must be strictly less than %s" % (name, maximum))
    return v


def paginate(items, limit, offset):
    """Sort by created_at asc (insertion seq tie-break) then window."""
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
