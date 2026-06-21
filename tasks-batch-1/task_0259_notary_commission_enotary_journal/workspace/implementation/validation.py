"""Request parsing, field validation, pagination, lookup, and serialization.

Validation ordering (PRD §2.9):
  auth(401) -> authz(403) -> existence(404) -> well-formed(400) ->
  semantic(422) -> state(409) -> business rules.

The 400-vs-422 split (PRD §2.9): a missing required field, a wrongly typed
value, or an out-of-set enum value -> ERR_INVALID_REQUEST (400). A value that
is syntactically present but semantically illegal (negative cents, term not in
{48,60,96,120}, interval end <= start) -> ERR_VALIDATION (422).
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
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field must be a string: %s" % name)
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


def require_enum(body, name, allowed, default=_MISSING):
    val = body.get(name, _MISSING)
    if val is _MISSING or val is None:
        if default is _MISSING:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_INVALID_REQUEST", "Invalid value for %s" % name)
    return val


def require_datetime(body, name):
    """Required ISO 8601 datetime. Missing/wrong-type -> 400; unparseable -> 400."""
    val = body.get(name, _MISSING)
    if val is _MISSING or val is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field must be a string datetime: %s" % name)
    dt = parse_iso8601(val)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "Field must be an ISO 8601 datetime: %s" % name)
    return dt


def non_negative_cents(value, name):
    """Semantic check: cents must be >= 0 -> ERR_VALIDATION (422)."""
    if value < 0:
        raise err("ERR_VALIDATION", "%s must be >= 0" % name)
    return value


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
    """Sort by created_at asc (seq tie-break) then slice."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
