"""Cross-cutting helpers: auth decorator, request-body validation, existence
lookups, pagination, and the mutation `touch` bookkeeping."""
from functools import wraps
from flask import request, g

import store
from errors import ApiError

ROLES = {"Member", "StoreClerk", "InventoryManager"}

# Map an entity-store key to the not-found error to raise.
NOT_FOUND = {
    "members": "ERR_MEMBER_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "stations": "ERR_STATION_NOT_FOUND",
    "bins": "ERR_BIN_NOT_FOUND",
    "containers": "ERR_CONTAINER_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "lines": "ERR_LINE_NOT_FOUND",
    "restock_tasks": "ERR_RESTOCK_TASK_NOT_FOUND",
    "subscriptions": "ERR_SUBSCRIPTION_NOT_FOUND",
    "vehicles": "ERR_VEHICLE_NOT_FOUND",
    "deliveries": "ERR_DELIVERY_NOT_FOUND",
}


# ---------------------------------------------------------------------------
# Auth + role gate (validation priorities 1 and 2)
# ---------------------------------------------------------------------------
def endpoint(roles):
    """Decorator: authenticate (401), enforce role membership (403), stash identity."""
    allowed = set(roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def owner_check(resource_member_id):
    """Priority-2 ownership: a Member may act only on resources they own."""
    if g.user_role == "Member" and resource_member_id != g.user_id:
        raise ApiError("ERR_UNAUTHORIZED", "member may act only on their own resources")


# ---------------------------------------------------------------------------
# Body access + validation (ERR_VALIDATION, 400)
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "request body must be a JSON object")
    return data


def field(body, name, required=False, kind=None, enum=None, default=None):
    if name not in body or body[name] is None:
        if required:
            raise ApiError("ERR_VALIDATION", "missing required field: %s" % name)
        return default
    v = body[name]
    if kind == "str":
        if not isinstance(v, str):
            raise ApiError("ERR_VALIDATION", "%s must be a string" % name)
    elif kind == "int":
        if isinstance(v, bool) or not isinstance(v, int):
            raise ApiError("ERR_VALIDATION", "%s must be an integer" % name)
    elif kind == "bool":
        if not isinstance(v, bool):
            raise ApiError("ERR_VALIDATION", "%s must be a boolean" % name)
    elif kind == "array":
        if not isinstance(v, list):
            raise ApiError("ERR_VALIDATION", "%s must be an array" % name)
    elif kind == "datetime":
        if not isinstance(v, str):
            raise ApiError("ERR_VALIDATION", "%s must be an ISO 8601 string" % name)
        try:
            return store.parse_dt(v)
        except Exception:
            raise ApiError("ERR_VALIDATION", "%s is not a valid ISO 8601 timestamp" % name)
    if enum is not None and v not in enum:
        raise ApiError("ERR_VALIDATION", "%s must be one of %s" % (name, sorted(enum)))
    return v


# ---------------------------------------------------------------------------
# Existence lookups (ERR_*_NOT_FOUND, 404)
# ---------------------------------------------------------------------------
def lookup(store_key, resource_id):
    rec = store.DB[store_key].get(resource_id)
    if rec is None:
        raise ApiError(NOT_FOUND[store_key])
    return rec


def require_fk(store_key, resource_id):
    """Validate a foreign-key value present in a body; None is treated as absent by callers."""
    if resource_id not in store.DB[store_key]:
        raise ApiError(NOT_FOUND[store_key])
    return store.DB[store_key][resource_id]


# ---------------------------------------------------------------------------
# Mutation bookkeeping
# ---------------------------------------------------------------------------
def stamp_new(rec, versioned=True):
    ts = store.now()
    rec["id"] = rec.get("id") or store.new_id()
    rec["created_at"] = ts
    rec["_seq"] = store.next_seq()
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = store.now()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Pagination + listing (PRD section 2.3)
# ---------------------------------------------------------------------------
def page_params():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def sort_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(records):
    limit, offset = page_params()
    ordered = sort_created(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
