"""Shared serialization, pagination, and input-validation helpers."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors

# Pagination defaults (§1.0 / PRD §2.3)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def round_half_up(value):
    """Round a numeric value to the nearest integer, half away from zero-up.

    PRD §2.7: a value exactly halfway rounds up to the larger magnitude.
    For monetary use the inputs are non-negative, so ROUND_HALF_UP suffices.
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_json_body():
    """Return the parsed JSON object body, or raise ERR_INVALID_REQUEST."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        body = request.get_json(silent=True)
    except Exception:
        raise errors.invalid_request("Malformed JSON body")
    if body is None:
        # An empty body is acceptable for action endpoints
        if not request.data:
            return {}
        raise errors.invalid_request("Malformed JSON body")
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def parse_pagination():
    """Parse limit/offset from query params; clamp/validate per §2.3.

    An out-of-range or non-integer limit/offset is an ERR_INVALID_REQUEST.
    """
    limit = request.args.get("limit")
    offset = request.args.get("offset")

    if limit is None:
        limit_val = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit_val = int(limit)
        except (ValueError, TypeError):
            raise errors.invalid_request("limit must be an integer")
        if limit_val < PAGE_LIMIT_MIN or limit_val > PAGE_LIMIT_MAX:
            raise errors.invalid_request(
                "limit must be between %d and %d" % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
            )

    if offset is None:
        offset_val = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset_val = int(offset)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer")
        if offset_val < 0:
            raise errors.invalid_request("offset must be >= 0")

    return limit_val, offset_val


def paginate(records, limit, offset):
    """Sort by creation order ascending and slice [offset:offset+limit]."""
    ordered = sorted(records, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ---- type/field validation primitives ----

def require_present(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request("Missing required field: %s" % field)
    return body[field]


def require_str(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return None
    val = body[field]
    if not isinstance(val, str):
        raise errors.invalid_request("Field %s must be a string" % field)
    return val


def require_int(body, field, required=True, minimum=None, maximum=None, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return default
    val = body[field]
    # bool is a subclass of int; reject it for integer fields
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field %s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise errors.invalid_request("Field %s must be >= %s" % (field, minimum))
    if maximum is not None and val > maximum:
        raise errors.invalid_request("Field %s must be <= %s" % (field, maximum))
    return val


def require_bool(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.invalid_request("Field %s must be a boolean" % field)
    return val


def require_enum(body, field, choices, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, str) or val not in choices:
        raise errors.invalid_request(
            "Field %s must be one of %s" % (field, sorted(choices))
        )
    return val


def require_number(body, field, required=True):
    """Accept an int or float (not bool) numeric value."""
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return None
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request("Field %s must be a number" % field)
    return val
