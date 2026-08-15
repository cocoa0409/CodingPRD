"""Request-body validation helpers.

Pipeline note (SCAFFOLD validations / PRD 2.10): malformed bodies, missing fields,
invalid enums and non-positive quantities are priority 41 — dead last. Endpoints
therefore run semantic checks first using the non-raising `valid_*` probes, and
only at the end call the `req_*` / `opt_*` helpers that raise ERR_INVALID_REQUEST.
"""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from util import is_valid_dt


def get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        # Defer the malformed-body error: treat as empty so that earlier-priority
        # semantic failures still mask the syntax failure (PRD 2.10).
        return {}
    return body


# ---------------------------------------------------------------------------
# Non-raising probes (used to gate semantic checks on well-formed inputs)
# ---------------------------------------------------------------------------

def valid_enum(v, allowed) -> bool:
    return isinstance(v, str) and v in allowed


def valid_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def valid_number(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def valid_pos_number(v) -> bool:
    return valid_number(v) and v > 0


def valid_nonneg_int(v) -> bool:
    return valid_int(v) and v >= 0


def valid_bool(v) -> bool:
    return isinstance(v, bool)


def valid_str(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def valid_dt(v) -> bool:
    return isinstance(v, str) and is_valid_dt(v)


# ---------------------------------------------------------------------------
# Raising field helpers (final validation stage — priority 41)
# ---------------------------------------------------------------------------

def req_str(body, field):
    v = body.get(field)
    if not valid_str(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def req_int(body, field, minimum=None, positive=False, non_negative=False):
    v = body.get(field)
    if not valid_int(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if positive and v <= 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be > 0")
    if non_negative and v < 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= 0")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {minimum}")
    return v


def opt_int(body, field, default=None, minimum=None, positive=False, non_negative=False):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, positive=positive, non_negative=non_negative)


def req_number(body, field, positive=False, non_negative=False):
    v = body.get(field)
    if not valid_number(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    if positive and v <= 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be > 0")
    if non_negative and v < 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= 0")
    return v


def opt_number(body, field, default=None, positive=False, non_negative=False):
    if field not in body or body.get(field) is None:
        return default
    return req_number(body, field, positive=positive, non_negative=non_negative)


def req_bool(body, field):
    v = body.get(field)
    if not valid_bool(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid boolean field: {field}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not valid_enum(v, allowed):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def req_dt(body, field):
    v = body.get(field)
    if not valid_dt(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid ISO datetime field: {field}")
    return v


def opt_dt(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not valid_dt(v):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO datetime field: {field}")
    return v


def req_enum_list(body, field, allowed, non_empty=True):
    v = body.get(field)
    if not isinstance(v, list) or (non_empty and len(v) == 0):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid array field: {field}")
    for item in v:
        if not valid_enum(item, allowed):
            raise_error(ERR_INVALID_REQUEST, f"field {field} contains invalid value: {item}")
    return list(v)


# ---------------------------------------------------------------------------
# Existence (priorities 5 and 6)
# ---------------------------------------------------------------------------

def require_path_resource(collection, rid):
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj


def check_body_fk(collection, body, field):
    """Priority 6: when the body carries the FK and it does not resolve -> 404.
    Absent/null fields are deferred to the final field-validation stage."""
    v = body.get(field)
    if v is None:
        return None
    obj = db[collection].get(v) if isinstance(v, str) else None
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"body reference {field} does not resolve: {v}")
    return obj


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def query_filter(field, allowed=None):
    """Optional query-string filter; 400 on a value outside a declared enum domain."""
    v = request.args.get(field)
    if v is None or v == "":
        return None
    if allowed is not None and v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"invalid value for filter {field}: {v}")
    return v
