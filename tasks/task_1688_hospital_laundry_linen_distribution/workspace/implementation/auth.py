"""Authentication / authorization (PRD 2.1)."""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE

ROLES = [
    "LinenManager",
    "EVSOperator",
    "LaundryVendor",
    "UnitClerk",
    "InfectionControlOfficer",
]

ALL_ROLES = list(ROLES)


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present; role is a declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not uid.strip():
        raise_err(ERR_UNAUTHENTICATED, "Missing or empty X-User-ID header")
    if not role or not role.strip():
        raise_err(ERR_UNAUTHENTICATED, "Missing or empty X-User-Role header")
    if role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "X-User-Role %s is not a declared role" % role)
    return uid, role


def authorize(role, allowed):
    """Priority 2: caller role in the endpoint's roles list."""
    if role not in allowed:
        raise_err(ERR_UNAUTHORIZED_ROLE,
                  "Role %s is not authorized for this endpoint" % role)
