"""Shared request/validation helpers used across route modules."""
from datetime import datetime

from flask import request

from errors import err


def get_json_body():
    """Return the parsed JSON body as a dict (empty dict if none)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


# ---------------------------------------------------------------------------
# Body field validation (priority 4)
#   ERR_INVALID_REQUEST (400): missing required field, wrong type, bad enum
#   ERR_VALIDATION_FAILED (422): numeric present + typed but out of declared range
# ---------------------------------------------------------------------------

def require_string(body, field, non_empty=True):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}.")
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string.")
    if non_empty and val.strip() == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be non-empty.")
    return val


def optional_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string.")
    return val


def require_enum(body, field, allowed):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}.")
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}.")
    return val


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}.")
    return val


def _is_int(val):
    # bool is a subclass of int; reject it as a non-integer for numeric fields.
    return isinstance(val, int) and not isinstance(val, bool)


def require_int(body, field, minimum=None):
    """Required integer field. Missing/wrong-type -> ERR_INVALID_REQUEST.
    Present and typed but below minimum -> ERR_VALIDATION_FAILED."""
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}.")
    val = body[field]
    if not _is_int(val):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    if minimum is not None and val < minimum:
        raise err("ERR_VALIDATION_FAILED", f"Field {field} must be >= {minimum}.")
    return val


def require_int_range(body, field, minimum, maximum):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}.")
    val = body[field]
    if not _is_int(val):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    if val < minimum or val > maximum:
        raise err("ERR_VALIDATION_FAILED",
                  f"Field {field} must be between {minimum} and {maximum}.")
    return val


def optional_int(body, field, default=0, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not _is_int(val):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    if minimum is not None and val < minimum:
        raise err("ERR_VALIDATION_FAILED", f"Field {field} must be >= {minimum}.")
    return val


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean.")
    return val


# ---------------------------------------------------------------------------
# Datetime / date parsing
# ---------------------------------------------------------------------------

def parse_iso_datetime(value, field):
    """Parse an ISO 8601 UTC instant. Raises ERR_INVALID_REQUEST on malformed."""
    if not isinstance(value, str) or value.strip() == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 datetime.")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 datetime.")


def require_iso_datetime(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}.")
    return require_string(body, field), parse_iso_datetime(body[field], field)


def hours_between(start_dt, end_dt):
    """Elapsed hours from start to end as a float."""
    return (end_dt - start_dt).total_seconds() / 3600.0


# ---------------------------------------------------------------------------
# Pagination (priority 4 -> ERR_PAGINATION_INVALID)
# ---------------------------------------------------------------------------

def parse_pagination():
    """Returns (limit, offset). limit default 10, range 1..100; offset default 0, >= 0.
    Out of band -> ERR_PAGINATION_INVALID (400)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_PAGINATION_INVALID", "limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_PAGINATION_INVALID", "offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (tie-break on creation sequence) then slice."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
