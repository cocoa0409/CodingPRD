"""Auth middleware, RBAC, ownership, and validation-pipeline primitives
(SCAFFOLD 1.4 / 1.7; PRD 2.1, 2.8, 2.10)."""
from flask import request

from db import DB
from errors import (
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_NOT_OWNER,
    ERR_UNAUTHENTICATED,
    raise_err,
)

ROLES = {
    "Customer",
    "SalesEngineer",
    "DepotManager",
    "FleetDispatcher",
    "FieldTechnician",
    "ClaimsAssessor",
    "PlatformAdmin",
}


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def auth():
    """Tier 1: headers present and role recognized (ERR_UNAUTHENTICATED)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(
            ERR_UNAUTHENTICATED,
            "Missing X-User-ID / X-User-Role headers or unrecognized role.",
        )
    return uid, role


def require_roles(role, allowed):
    """Tier 2: role permitted for endpoint (ERR_FORBIDDEN)."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, "Role %s is not permitted for this endpoint." % role)


def get_or_404(table, rid, label="resource"):
    rec = table.get(rid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "No %s exists with id %s." % (label, rid))
    return rec


def check_customer_owns(rec_customer_id, uid):
    """Tier 2 ownership: Customer role may only touch own resources."""
    if rec_customer_id != uid:
        raise_err(ERR_NOT_OWNER, "Resource belongs to a different customer.")


def customer_scope_filter(role, uid):
    """For list endpoints: Customer role is force-scoped to its own id."""
    return uid if role == "Customer" else None
