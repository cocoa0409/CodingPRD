"""Shared request/validation helpers used across route modules."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import clock
from errors import err


def get_json_body():
    """Return the parsed JSON body as a dict.

    A missing/empty body is treated as an empty object. A malformed JSON body
    (present but not parseable, or not an object) yields ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise err("ERR_INVALID_REQUEST", "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: {}".format(f))


def require_enum(value, allowed, field_name):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "Invalid value for {}".format(field_name))


def require_string(value, field_name):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", "Field {} must be a non-empty string".format(field_name))


def require_int(value, field_name):
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "Field {} must be an integer".format(field_name))
    return value


def require_nonneg_int(value, field_name):
    require_int(value, field_name)
    if value < 0:
        raise err("ERR_INVALID_REQUEST", "Field {} must be >= 0".format(field_name))
    return value


def require_positive_int(value, field_name):
    require_int(value, field_name)
    if value <= 0:
        raise err("ERR_INVALID_REQUEST", "Field {} must be > 0".format(field_name))
    return value


def require_number(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field {} must be a number".format(field_name))
    return value


def require_bool(value, field_name):
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", "Field {} must be a boolean".format(field_name))
    return value


def parse_datetime_field(value, field_name):
    try:
        return clock.parse_iso(value)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Field {} must be an ISO 8601 datetime".format(field_name))


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3).

    limit defaults to 10, min 1, max 100. offset defaults to 0, min 0.
    Out-of-range or malformed values yield ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Apply offset/limit to an already-sorted list. Returns (page, total)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_by_created(items):
    """Ascending created_at (PRD §2.3). The internal monotonic _seq is the
    stable tie-break so insertion order is preserved when timestamps collide
    under a fixed logical clock."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


# Internal-only keys that must never appear in API responses.
_INTERNAL_KEYS = ("_seq",)


def serialize(record):
    """Return a copy of a stored record with internal-only keys removed."""
    return {k: v for k, v in record.items() if k not in _INTERNAL_KEYS}


def serialize_list(records):
    return [serialize(r) for r in records]


def round_half_up(value):
    """Round a numeric value half-up to the nearest whole integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
