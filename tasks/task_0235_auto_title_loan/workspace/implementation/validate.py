"""Request body validation helpers (PRD 2.6).

Precedence within the request-validation group:
  - missing/mistyped field or bad enum member -> ERR_INVALID_REQUEST (422)
  - correctly typed but out-of-range value    -> ERR_VALIDATION_RANGE (422)
"""
from flask import request

from errors import err


def get_body():
    """Parse the JSON request body, returning {} when absent.

    A body that is present but not a JSON object is ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def require_str(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "missing field: %s" % field)
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "field %s must be a non-empty string" % field)
    return v


def require_int(body, field):
    """Require an integer field (presence + type). Range checks are separate.

    Booleans are rejected (bool is a subclass of int in Python).
    """
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "missing field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "field %s must be an integer" % field)
    return v


def require_enum(body, field, members):
    v = require_str(body, field)
    if v not in members:
        raise err("ERR_INVALID_REQUEST", "field %s must be one of %s" % (field, sorted(members)))
    return v


def parse_pagination():
    """Parse limit/offset query params (PRD 2.3).

    limit defaults 10, min 1, max 100. offset defaults 0.
    Out-of-range or non-integer values raise ERR_INVALID_REQUEST.
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
            raise err("ERR_INVALID_REQUEST", "limit out of range [1, 100]")

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
    """Slice an already-sorted list of public dicts."""
    return items[offset:offset + limit]
