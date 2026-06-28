"""Shared request-parsing, validation, pagination, and serialization helpers."""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors


# ---------------------------------------------------------------------------
# Body parsing & field validation (ERR_VALIDATION = 400)
# ---------------------------------------------------------------------------

def get_body():
    """Return the parsed JSON body as a dict. Missing body -> {}. Malformed -> 400."""
    if request.method in ("POST", "PATCH", "PUT"):
        if request.content_length in (None, 0) and not (request.data or b""):
            return {}
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise errors.validation("Malformed JSON body")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise errors.validation("Request body must be a JSON object")
        return data
    return {}


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.validation("Missing required field: " + name)
    return body[name]


def require_str(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val == "":
        raise errors.validation("Field must be a non-empty string: " + name)
    return val


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str):
        raise errors.validation("Field must be a string: " + name)
    return val


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def require_number(body, name):
    val = require_field(body, name)
    if not _is_number(val):
        raise errors.validation("Field must be a number: " + name)
    return val


def opt_number(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not _is_number(val):
        raise errors.validation("Field must be a number: " + name)
    return val


def require_bool(body, name):
    val = require_field(body, name)
    if not isinstance(val, bool):
        raise errors.validation("Field must be a boolean: " + name)
    return val


def opt_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise errors.validation("Field must be a boolean: " + name)
    return val


def require_int(body, name):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.validation("Field must be an integer: " + name)
    return val


def opt_int(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.validation("Field must be an integer: " + name)
    return val


def require_enum(body, name, allowed):
    val = require_str(body, name)
    if val not in allowed:
        raise errors.validation("Field %s must be one of %s" % (name, sorted(allowed)))
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
            raise errors.validation("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.validation("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """items is a list already sorted by created_at asc. Returns (page, total)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_by_created(items):
    # created_at is ISO 8601 with ms; lexicographic == chronological. Tie-break
    # on insertion is preserved because Python sort is stable.
    return sorted(items, key=lambda r: r["created_at"])


# ---------------------------------------------------------------------------
# Money / rounding (PRD §2.7): whole dollars, round half up
# ---------------------------------------------------------------------------

def round_dollars(value):
    """Round half up to a whole-dollar integer."""
    d = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)
