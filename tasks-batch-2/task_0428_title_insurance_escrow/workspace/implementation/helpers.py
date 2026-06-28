"""Shared request-parsing, validation, pagination, and money helpers.

Body-shape violations map to ERR_INVALID_REQUEST (422) per PRD §2.8 priority 4.
"""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors


# ---------------------------------------------------------------------------
# Body parsing & field validation (ERR_INVALID_REQUEST = 422)
# ---------------------------------------------------------------------------

def get_body():
    """Return the parsed JSON body as a dict. Missing body -> {}. Malformed -> 422."""
    if request.method in ("POST", "PATCH", "PUT"):
        if request.content_length in (None, 0) and not (request.data or b""):
            return {}
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise errors.invalid_request("Malformed JSON body")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise errors.invalid_request("Request body must be a JSON object")
        return data
    return {}


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request("Missing required field: " + name)
    return body[name]


def require_str(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request("Field must be a non-empty string: " + name)
    return val


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str):
        raise errors.invalid_request("Field must be a string: " + name)
    return val


def require_int(body, name):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field must be an integer: " + name)
    return val


def require_int_min(body, name, minimum):
    val = require_int(body, name)
    if val < minimum:
        raise errors.invalid_request(
            "Field %s must be >= %d" % (name, minimum))
    return val


def opt_int(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field must be an integer: " + name)
    return val


def require_number(body, name):
    """Require a JSON number (int or float, not bool)."""
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request("Field must be a number: " + name)
    return val


def require_bool(body, name):
    val = require_field(body, name)
    if not isinstance(val, bool):
        raise errors.invalid_request("Field must be a boolean: " + name)
    return val


def opt_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise errors.invalid_request("Field must be a boolean: " + name)
    return val


def require_enum(body, name, allowed):
    val = require_str(body, name)
    if val not in allowed:
        raise errors.invalid_request(
            "Field %s must be one of %s" % (name, sorted(allowed)))
    return val


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(
            "Field %s must be one of %s" % (name, sorted(allowed)))
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10 min 1 max 100; offset default 0
# ---------------------------------------------------------------------------

def parse_pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def sort_by_created(items):
    """Sort by created_at asc (PRD §2.3), tie-broken by insertion sequence.

    The logical clock does not advance per write, so multiple resources can share
    a created_at instant; the monotonic _seq field preserves creation order.
    """
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(items, limit, offset):
    """items is a list already sorted. Returns (page, total)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Money / rounding (PRD §2.6): integer cents, round half up
# ---------------------------------------------------------------------------

def round_half_up(value):
    """Round half up (away from zero on .5) to a whole integer (cents)."""
    d = Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)
