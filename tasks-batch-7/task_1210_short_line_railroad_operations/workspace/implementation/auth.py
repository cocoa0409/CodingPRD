"""Authentication / authorization per PRD section 2.1.

Every request carries X-User-ID and X-User-Role. Nine recognized roles.
Entity-backed roles: Conductor (X-User-ID is a CrewMember id) and
CustomerRep (X-User-ID is a Customer id). The other seven roles are opaque.
"""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ROLES = {
    "SystemAdmin",
    "Dispatcher",
    "CrewCaller",
    "Conductor",
    "TrackInspector",
    "SettlementClerk",
    "RegulatorOfficer",
    "CustomerRep",
    "GrantManager",
}


def authenticate():
    """Band 1: both headers present and role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(401, ERR_UNAUTHENTICATED,
                       "missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def require_role(role, allowed):
    """Band 2: role must be listed for the endpoint."""
    if role not in allowed:
        raise ApiError(403, ERR_FORBIDDEN_ROLE,
                       "role %s is not authorized for this endpoint" % role)


def require_owner(owner_id, uid):
    """Entity-backed identity check (Conductor -> CrewMember, CustomerRep -> Customer)."""
    if owner_id != uid:
        raise ApiError(403, ERR_FORBIDDEN_ROLE,
                       "entity-backed identity does not match the targeted resource")
