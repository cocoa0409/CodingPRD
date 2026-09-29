"""Actor resolution, role authorization and store scoping (PRD 2.1, 2.11 steps 1-4)."""

from flask import request

import db
from errors import ApiError

ROLE_PREFIX = {
    "lc-": "LiquidationConsultant",
    "rc-": "RetailerController",
    "co-": "ComplianceOfficer",
    "so-": "SystemOperator",
}

STORE_MANAGER = "StoreManager"


def raw_user_id():
    value = request.headers.get("X-User-ID")
    if value is None:
        return None
    return value.strip()


def resolve_actor(optional=False):
    """Step 1 (presence) then step 2 (resolution). Returns (user_id, role)."""
    user_id = raw_user_id()
    if not user_id:
        if optional:
            return None, None
        raise ApiError("ERR_MISSING_USER_HEADER")
    for prefix, role in ROLE_PREFIX.items():
        if user_id.startswith(prefix) and len(user_id) > len(prefix):
            return user_id, role
    store = db.get("stores", user_id)
    if store is not None:
        return user_id, STORE_MANAGER
    raise ApiError("ERR_UNKNOWN_ACTOR")


def authorize(role, allowed_roles):
    """Step 3."""
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")


def begin(allowed_roles):
    """Steps 1-3 in one call. Returns (user_id, role)."""
    user_id, role = resolve_actor()
    authorize(role, allowed_roles)
    return user_id, role


def scope_store(user_id, role, store_id):
    """Step 4: a StoreManager may only address its own store id."""
    if role != STORE_MANAGER:
        return
    if store_id is None or store_id != user_id:
        raise ApiError("ERR_STORE_SCOPE_VIOLATION")


def scope_child(user_id, role, row):
    """Step 4 for a child row; a missing row defers to the existence check."""
    if role != STORE_MANAGER:
        return
    if row is None:
        return
    if row.get("store_id") != user_id:
        raise ApiError("ERR_STORE_SCOPE_VIOLATION")


def deny_self_decision(user_id, row, field):
    """Step 5: segregation of duties. Missing rows defer to the existence check."""
    if row is None:
        return
    submitter = row.get(field)
    if submitter is not None and submitter == user_id:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN")
