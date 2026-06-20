"""Auth header extraction and RBAC (PRD 2.1, 2.10, scaffold 1.4/1.7).

Every request must carry X-User-ID and X-User-Role. If X-User-Role is missing or
not a recognized role -> ERR_UNAUTHENTICATED (401). If the role is recognized but
not permitted for the operation -> ERR_FORBIDDEN (403).

Roles: Coordinator, Broker, Driver, Auditor. Coordinator/Broker/Auditor identities
are opaque; Driver is entity-backed (X-User-ID is the acting Driver row's id).
"""
from flask import request

from errors import err

RECOGNIZED_ROLES = {"Coordinator", "Broker", "Driver", "Auditor"}


def get_role():
    return request.headers.get("X-User-Role")


def get_user_id():
    return request.headers.get("X-User-ID")


def authenticate():
    """Validate the role header. Returns the role string or raises."""
    role = get_role()
    if not role or role not in RECOGNIZED_ROLES:
        raise err("ERR_UNAUTHENTICATED", "X-User-Role header missing or not a recognized role")
    return role


def require_roles(*allowed):
    """Authenticate then check the role is in the allowed set for this operation."""
    role = authenticate()
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
    return role
