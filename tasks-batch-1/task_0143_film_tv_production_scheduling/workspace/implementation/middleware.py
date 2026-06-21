"""Auth header extraction and RBAC enforcement.

Per PRD section 2.1: every request carries X-User-ID and X-User-Role. The five
recognized roles are LineProducer, FirstAD, PayrollCoordinator, PostSupervisor,
UnionRep. X-User-ID is opaque and never compared to entity ids.
"""
from flask import request

from errors import err

KNOWN_ROLES = {
    "LineProducer",
    "FirstAD",
    "PayrollCoordinator",
    "PostSupervisor",
    "UnionRep",
}


def authenticate():
    """Validate the auth headers (priority 1). Returns the role string.

    Raises ERR_UNAUTHENTICATED when X-User-ID is missing, X-User-Role is missing,
    or X-User-Role is not a known role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return role


def authorize(role, allowed_roles):
    """RBAC check (priority 2). Raises ERR_FORBIDDEN if role not permitted."""
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN", "Role is not permitted to perform this operation.")
