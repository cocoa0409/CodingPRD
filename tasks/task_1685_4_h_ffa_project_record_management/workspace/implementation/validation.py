"""Request-shape validation helpers (validation priority 14 -> ERR_INVALID_REQUEST)
and pagination parsing (PRD section 2.3)."""

import re
from datetime import date

from flask import request

import clock
from errors import ApiError, ERR_INVALID_REQUEST

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_body():
    """JSON body as a dict; anything else is treated as an empty object so the
    required-field checks fire uniformly."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def _bad(name, why):
    raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s': %s" % (name, why))


def present(data, name):
    if name not in data or data[name] is None:
        _bad(name, "required field is missing")
    return data[name]


def as_str(data, name):
    value = present(data, name)
    if not isinstance(value, str) or value == "":
        _bad(name, "must be a non-empty string")
    return value


def as_int(data, name):
    value = present(data, name)
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    return value


def as_num(data, name):
    value = present(data, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    return value


def as_bool(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    if not isinstance(data[name], bool):
        _bad(name, "must be a boolean")
    return data[name]


def as_enum(data, name, allowed):
    value = present(data, name)
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of {%s}" % ", ".join(allowed))
    return value


def as_int_range(data, name, lo=None, hi=None):
    value = as_int(data, name)
    if lo is not None and value < lo:
        _bad(name, "must be >= %d" % lo)
    if hi is not None and value > hi:
        _bad(name, "must be <= %d" % hi)
    return value


def as_num_range(data, name, lo=None, hi=None):
    value = as_num(data, name)
    if lo is not None and value < lo:
        _bad(name, "must be >= %s" % lo)
    if hi is not None and value > hi:
        _bad(name, "must be <= %s" % hi)
    return value


def as_date_str(data, name):
    value = present(data, name)
    if not isinstance(value, str) or not _DATE_RE.match(value):
        _bad(name, "must be an ISO 8601 date (YYYY-MM-DD)")
    try:
        date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        _bad(name, "must be a valid calendar date (YYYY-MM-DD)")
    return value


def as_datetime_str(data, name):
    value = present(data, name)
    if clock.parse_iso(value) is None:
        _bad(name, "must be an ISO 8601 UTC timestamp")
    return value


def pagination_params():
    """limit (default 10, min 1, max 100) and offset (default 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'limit': must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'limit': must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'offset': must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'offset': must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items: full sorted list. Returns (page, pagination-meta)."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def sort_by_creation(records):
    """Default list ordering: creation timestamp ascending (PRD section 2.3).
    _seq breaks ties deterministically in insertion order because the logical
    clock can be frozen across multiple creates."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
