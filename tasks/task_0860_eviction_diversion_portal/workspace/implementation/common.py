"""Auth, request-body parsing, validation and pagination helpers."""

from flask import g, request

import store
from errors import ApiError

ROLES = {"Clerk", "Landlord", "Tenant", "Mediator", "Judge", "ProgramAdmin", "Sheriff"}


# ---------------------------------------------------------------------------
# Authentication / authorization
# ---------------------------------------------------------------------------
def authorize(allowed_roles, exempt_when_no_auth=False):
    """Validate auth headers and role.  Stores role/uid on flask.g.

    Priority 1: ERR_UNAUTHENTICATED (missing/invalid headers)
    Priority 2 (role part): ERR_UNAUTHORIZED (role not permitted)
    """
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")

    if exempt_when_no_auth and not role and not uid:
        g.role = "Clerk"
        g.uid = None
        return
    if not role or not uid or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation" % role)
    g.role = role
    g.uid = uid


def check_case_ownership(case):
    """Ownership check for entity-backed roles (priority 2, ownership part)."""
    if g.role == "Landlord" and case.get("landlord_id") != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "Landlord does not own this case")
    if g.role == "Tenant" and case.get("tenant_id") != g.uid:
        raise ApiError("ERR_UNAUTHORIZED", "Tenant does not own this case")


def owns_case(case):
    if g.role == "Landlord":
        return case.get("landlord_id") == g.uid
    if g.role == "Tenant":
        return case.get("tenant_id") == g.uid
    return True


# ---------------------------------------------------------------------------
# Body parsing / validation (priority 3: ERR_VALIDATION)
# ---------------------------------------------------------------------------
def get_body():
    if request.data and len(request.data) > 0:
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            data = None
    else:
        data = {}
    if data is None:
        raise ApiError("ERR_VALIDATION", "Request body must be valid JSON")
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", "Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", "Field %s must be a non-empty string" % field)
    return v


def require_enum(body, field, allowed):
    v = require(body, field)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def require_int(body, field, minimum=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", "Field %s must be >= %s" % (field, minimum))
    return v


def optional_int(body, field, default=0, minimum=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum=minimum)


def require_dt(body, field):
    v = require(body, field)
    try:
        dt = store.parse_dt(v)
    except Exception:
        raise ApiError("ERR_VALIDATION", "Field %s must be an ISO-8601 datetime" % field)
    if dt is None:
        raise ApiError("ERR_VALIDATION", "Field %s must be an ISO-8601 datetime" % field)
    return dt


def optional_dt(body, field):
    if field not in body or body[field] is None:
        return None
    return require_dt(body, field)


# ---------------------------------------------------------------------------
# Existence (priority 4: ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def lookup(collection, ident):
    ent = store.db[collection].get(ident)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", "%s %s not found" % (collection, ident))
    return ent


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def pagination_params():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items already filtered; sort by (created_at, _seq) ascending."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
