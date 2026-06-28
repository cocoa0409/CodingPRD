"""Shared request-body and query helpers.

Body validation (ERR_INVALID_REQUEST / 422) runs at priority 4 — AFTER auth,
role, and existence, but BEFORE state and business rules (PRD §2.6).
"""
from errors import err


def get_body():
    """Return the request JSON body as a dict (empty dict when absent).

    A malformed/non-object JSON body is treated as ERR_INVALID_REQUEST.
    """
    from flask import request
    if request.content_length in (None, 0) and not (request.data or b"").strip():
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        # Body was present but unparsable, or an empty string.
        if (request.data or b"").strip():
            raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string." % field)
    return val


def require_int(body, field):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    return val


def require_enum(body, field, members):
    val = require(body, field)
    if val not in members:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s." % (field, sorted(members)))
    return val


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    return val


def optional_enum(body, field, members, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if val not in members:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s." % (field, sorted(members)))
    return val


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return val


def parse_pagination(args):
    """Parse limit/offset from query args (PRD §2.3).

    limit: default 10, min 1, max 100. offset: default 0, min 0.
    Invalid (non-integer) values -> ERR_INVALID_REQUEST.
    Out-of-range values are clamped to the bounds.
    """
    limit = _parse_int_arg(args, "limit", 10)
    offset = _parse_int_arg(args, "offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_int_arg(args, name, default):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "Query parameter %s must be an integer." % name)


def paginate(items, limit, offset):
    """Slice an ordered list, returning (page, total_count)."""
    total = len(items)
    return items[offset:offset + limit], total
