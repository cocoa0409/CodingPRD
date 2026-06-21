"""Shared request helpers: auth/RBAC, body parsing, validation, pagination,
serialization. PRD §2.1, §2.3, §2.8."""
from flask import request

import db
from errors import err

ROLES = {"ShipperOps", "CarrierOps", "DockOps", "FreightAuditor"}


def require_auth():
    """PRD §2.1: X-User-ID and X-User-Role headers must be present and non-empty.
    Returns the role string. Raises ERR_MISSING_USER_CONTEXT (401) otherwise."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise err("ERR_MISSING_USER_CONTEXT", "X-User-ID and X-User-Role headers are required")
    return user_role


def require_role(role, allowed):
    """PRD §2.1/§2.8: role authorization. `allowed` is a set/list of role names.
    Raises ERR_FORBIDDEN_ROLE (403) if the caller's role is not permitted."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s is not permitted to perform this operation" % role)


def auth(allowed):
    """Run priority 1 (auth headers) then priority 2 (role) checks. Returns role."""
    role = require_auth()
    require_role(role, allowed)
    return role


def get_json_body():
    """Parse the JSON request body, returning {} for an empty body.
    A malformed JSON document is treated as an invalid request (PRD §2.8)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)


def as_int(body, name, required=True, default=None):
    """Extract an integer field; bool is rejected (JSON true/false is not an int)."""
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    return val


def as_number(body, name, required=True, default=None):
    """Extract a numeric (int or float) field; bool rejected."""
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % name)
    return val


def as_str(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    val = body[name]
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % name)
    return val


def as_enum(body, name, allowed, required=True, default=None):
    val = as_str(body, name, required=required, default=default)
    if val is None:
        return None
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (name, sorted(allowed)))
    return val


# ---- Pagination (PRD §2.3) ----

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def _parse_int_param(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "Pagination parameter must be an integer")


def parse_pagination():
    """limit defaults 10 (min 1, max 100); offset defaults 0 (PRD §2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGE_DEFAULT_LIMIT
    else:
        limit = _parse_int_param(limit_raw)
        if limit < PAGE_MIN_LIMIT:
            limit = PAGE_MIN_LIMIT
        elif limit > PAGE_MAX_LIMIT:
            limit = PAGE_MAX_LIMIT

    if offset_raw is None:
        offset = PAGE_DEFAULT_OFFSET
    else:
        offset = _parse_int_param(offset_raw)
        if offset < 0:
            offset = 0

    return limit, offset


def paginate(records):
    """Sort by created_at ASC (tie-broken by insertion sequence) then slice.
    Returns (page_items, pagination_meta) with limit/offset/total_count/has_more."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta


def clean(record):
    """Strip private fields (those beginning with '_') for serialization."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def clean_all(records):
    return [clean(r) for r in records]
