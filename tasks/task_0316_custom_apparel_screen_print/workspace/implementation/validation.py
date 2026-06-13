"""Request parsing, field validation, and pagination (PRD §2.3, §2.6, §2.10).

Validation ordering (PRD §2.10): auth(400) -> authz(403) -> existence(404) ->
body well-formed(400, ERR_INVALID_REQUEST) -> state(409) -> business rules.

This API folds all malformed-body checks into a single 400 tier
(ERR_INVALID_REQUEST): bad enum members, non-positive-integer quantities, an
empty size_run, and colors/sizes not drawn from the style's catalog all raise
ERR_INVALID_REQUEST.
"""
from flask import request

from clock import parse_iso8601
from errors import err

_MISSING = object()


def get_body():
    """Return the JSON body as a dict, or {} when absent."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_str(body, name):
    val = body.get(name, _MISSING)
    if val is _MISSING or val is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "Field must be a non-empty string: %s" % name)
    return val


def optional_str(body, name, default=None):
    val = body.get(name, _MISSING)
    if val is _MISSING or val is None:
        return default
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "Field must be a non-empty string: %s" % name)
    return val


def require_int(body, name, default=_MISSING):
    """Require an integer field. bool is rejected (bool is a subtype of int)."""
    val = body.get(name, _MISSING)
    if val is _MISSING or val is None:
        if default is _MISSING:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field must be an integer: %s" % name)
    return val


def require_positive_int(body, name, default=_MISSING):
    val = require_int(body, name, default)
    if val <= 0:
        raise err("ERR_INVALID_REQUEST", "Field must be a positive integer: %s" % name)
    return val


def require_number(body, name, default=_MISSING):
    """Require a numeric (int or float) field. bool rejected."""
    val = body.get(name, _MISSING)
    if val is _MISSING or val is None:
        if default is _MISSING:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field must be a number: %s" % name)
    return val


def require_bool(body, name, default=_MISSING):
    val = body.get(name, _MISSING)
    if val is _MISSING or val is None:
        if default is _MISSING:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field must be a boolean: %s" % name)
    return val


def require_enum(body, name, allowed, default=_MISSING):
    val = body.get(name, _MISSING)
    if val is _MISSING or val is None:
        if default is _MISSING:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_INVALID_REQUEST", "Invalid value for %s" % name)
    return val


def require_str_array(body, name):
    val = body.get(name, _MISSING)
    if val is _MISSING or val is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    if not isinstance(val, list) or not val:
        raise err("ERR_INVALID_REQUEST", "Field must be a non-empty array: %s" % name)
    for item in val:
        if not isinstance(item, str) or item == "":
            raise err("ERR_INVALID_REQUEST", "Array must contain non-empty strings: %s" % name)
    return val


def require_datetime(body, name):
    """Required ISO 8601 datetime. Missing/wrong-type/unparseable -> 400."""
    val = body.get(name, _MISSING)
    if val is _MISSING or val is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field must be a string datetime: %s" % name)
    dt = parse_iso8601(val)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "Field must be an ISO 8601 datetime: %s" % name)
    return dt


# ---- Pagination (PRD §2.3) ----

def parse_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_val = 10
    else:
        try:
            limit_val = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit_val < 1 or limit_val > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range [1,100]")
    if offset is None:
        offset_val = 0
    else:
        try:
            offset_val = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset_val < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit_val, offset_val


def paginate(records, limit, offset):
    """Sort by created_at asc (seq tie-break) then slice (PRD §2.3)."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def bool_arg(name, default=False):
    raw = request.args.get(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes")
