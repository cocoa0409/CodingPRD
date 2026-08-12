"""Request-scoped helpers: auth, role checks, body/field validation,
pagination. Validation ordering follows PRD 2.8 (auth -> forbidden ->
not-found -> stale -> shape -> cross-scope -> state -> SoD -> safety ->
temporal -> structural -> fiscal); individual endpoints compose these
helpers in that order.
"""
from flask import request

from errors import bad_request, forbidden, not_found, unauthenticated
from util import parse_date, parse_iso

ROLES = (
    "TurnaroundManager",
    "Planner",
    "PermitCoordinator",
    "ContractorSupervisor",
    "CostController",
    "OperationsRep",
)
ANY_ROLE = ROLES

MISSING = object()


# ---------------------------------------------------------------- auth (p1/p2)
def actor():
    """Validate the two auth headers; returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        unauthenticated("X-User-ID and a recognized X-User-Role header are required")
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        forbidden("Role %s is not permitted for this endpoint" % role)


# ------------------------------------------------------------------ body/shape
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad_request("Request body must be a JSON object")
    return data


def req_field(b, name):
    v = b.get(name, MISSING)
    if v is MISSING or v is None:
        bad_request("Missing required field: %s" % name)
    return v


def opt_field(b, name, default=None):
    v = b.get(name, MISSING)
    if v is MISSING or v is None:
        return default
    return v


def as_str(v, name):
    if not isinstance(v, str) or not v:
        bad_request("Field %s must be a non-empty string" % name)
    return v


def as_int(v, name, minimum=None):
    if isinstance(v, bool) or not isinstance(v, int):
        bad_request("Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        bad_request("Field %s must be >= %d" % (name, minimum))
    return v


def as_num(v, name, gt=None, ge=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad_request("Field %s must be a number" % name)
    if gt is not None and not v > gt:
        bad_request("Field %s must be > %s" % (name, gt))
    if ge is not None and not v >= ge:
        bad_request("Field %s must be >= %s" % (name, ge))
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        bad_request("Field %s must be a boolean" % name)
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        bad_request("Field %s must be one of %s" % (name, ", ".join(allowed)))
    return v


def as_dt(v, name):
    dt = parse_iso(v)
    if dt is None:
        bad_request("Field %s must be an ISO-8601 datetime" % name)
    return dt


def as_date(v, name):
    d = parse_date(v)
    if d is None:
        bad_request("Field %s must be a YYYY-MM-DD date" % name)
    return d


def as_str_list(v, name):
    if not isinstance(v, list) or any(not isinstance(x, str) or not x for x in v):
        bad_request("Field %s must be an array of strings" % name)
    return v


# ------------------------------------------------------------------ existence
def get_or_404(store, entity_id, label="Resource"):
    entity = store.get(entity_id)
    if entity is None:
        not_found("%s not found: %s" % (label, entity_id))
    return entity


# ----------------------------------------------------------------- pagination
def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad_request("limit must be an integer")
        if limit < 1:
            bad_request("limit must be >= 1")
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad_request("offset must be an integer")
        if offset < 0:
            bad_request("offset must be >= 0")
    return limit, offset


def paged(items, limit, offset):
    """items must already be sorted (created_at ascending)."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def sorted_by_created(items):
    return sorted(items, key=lambda e: e["_seq"])
