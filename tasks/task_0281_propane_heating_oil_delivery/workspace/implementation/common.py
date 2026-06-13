"""Shared helpers: pagination, body-field validation, serialization."""
from flask import request

import errors

# Pagination defaults (PRD §2.3 / SCAFFOLD response_envelope.pagination_defaults)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination():
    """Read limit/offset from the query string with PRD §2.3 rules.

    limit defaults to 10, must be 1..100. offset defaults to 0, must be >= 0.
    Out-of-range or non-integer values -> ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise errors.ApiError(
                errors.ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100"
            )

    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400, "offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Return the page slice. Caller already has total_count = len(items)."""
    return items[offset:offset + limit]


def sort_by_created(records):
    """Default list ordering: created_at ascending (PRD §2.3).

    created_at strings are ISO-8601 with fixed precision so lexical sort matches
    chronological order; ties broken by id for determinism.
    """
    return sorted(records, key=lambda r: (r.get("created_at", ""), r.get("id", "")))


# --- Body field validators (all raise ERR_INVALID_REQUEST on failure) ---

def _invalid(msg):
    raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400, msg)


def require_field(body, name):
    if name not in body or body[name] is None:
        _invalid("Missing required field: %s" % name)
    return body[name]


def require_string(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or not val.strip():
        _invalid("Field %s must be a non-empty string" % name)
    return val


def require_int(body, name, minimum=None):
    val = require_field(body, name)
    # Reject bool (a subclass of int) and non-int types.
    if isinstance(val, bool) or not isinstance(val, int):
        _invalid("Field %s must be an integer" % name)
    if minimum is not None and val < minimum:
        _invalid("Field %s must be >= %s" % (name, minimum))
    return val


def optional_int(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        _invalid("Field %s must be an integer" % name)
    if minimum is not None and val < minimum:
        _invalid("Field %s must be >= %s" % (name, minimum))
    if maximum is not None and val > maximum:
        _invalid("Field %s must be <= %s" % (name, maximum))
    return val


def optional_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        _invalid("Field %s must be a boolean" % name)
    return val


def require_enum(body, name, allowed):
    val = require_field(body, name)
    if not isinstance(val, str) or val not in allowed:
        _invalid("Field %s must be one of %s" % (name, sorted(allowed)))
    return val


def optional_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str) or val not in allowed:
        _invalid("Field %s must be one of %s" % (name, sorted(allowed)))
    return val


def require_iso_datetime(body, name):
    """Required ISO-8601 datetime field; returns the raw string."""
    from clock import parse_iso
    val = require_field(body, name)
    if not isinstance(val, str) or parse_iso(val) is None:
        _invalid("Field %s must be an ISO 8601 datetime" % name)
    return val
