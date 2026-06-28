"""Request-body and query-param validation helpers (PRD §2.3, §3.14)."""
from flask import request

import errors

# Pagination defaults per scaffold response_envelope.pagination_defaults.
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def body():
    """Return the JSON body as a dict; raise ERR_INVALID_REQUEST if malformed."""
    if request.data is None or request.data == b"":
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def require(data, field, types=None):
    if field not in data or data[field] is None:
        raise errors.invalid_request("Missing required field: %s" % field)
    val = data[field]
    if types is not None and not _is_type(val, types):
        raise errors.invalid_request("Field %s has the wrong type." % field)
    return val


def optional(data, field, types=None, default=None):
    if field not in data or data[field] is None:
        return default
    val = data[field]
    if types is not None and not _is_type(val, types):
        raise errors.invalid_request("Field %s has the wrong type." % field)
    return val


def _is_type(val, types):
    # bool is a subclass of int; guard so an int field rejects True/False and vice versa.
    if types is bool:
        return isinstance(val, bool)
    if types is int:
        return isinstance(val, int) and not isinstance(val, bool)
    if types is float:
        # accept int or float as a number, but not bool
        return (isinstance(val, (int, float)) and not isinstance(val, bool))
    if isinstance(types, tuple):
        # number-ish tuple handling
        if int in types or float in types:
            if isinstance(val, bool):
                return False
        return isinstance(val, types) and not (isinstance(val, bool) and bool not in types)
    return isinstance(val, types)


def enum(value, allowed, field):
    if value not in allowed:
        raise errors.invalid_request(
            "Field %s must be one of %s." % (field, sorted(allowed))
        )
    return value


def pagination():
    """Parse limit/offset query params with defaults; raise ERR_INVALID_REQUEST on bad values."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise errors.invalid_request(
                "limit must be between %d and %d." % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
            )

    if offset_raw is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0.")

    return limit, offset


def paginate(rows, limit, offset):
    """Sort by (created_at ASC, seq ASC), slice, return (items, total_count)."""
    ordered = sorted(rows, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
