"""Auth middleware — per PRD §2.1 and scaffold validations priority 1-2.

Every request must carry X-User-ID and X-User-Role. X-User-Role must map to one
of the six declared roles. X-User-ID is opaque and not tied to any entity.
"""

from flask import request

from errors import err_forbidden, err_unauthenticated

ROLES = {
    "MillPlanner",
    "SpinningSupervisor",
    "DyeHouseOperator",
    "QualityInspector",
    "CustomerServiceRep",
    "MillAdmin",
}


def get_role():
    """Return the caller's role, or raise ERR_UNAUTHENTICATED."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise err_unauthenticated()
    return role


def require_roles(*allowed):
    """Validate auth (priority 1) then authorization (priority 2)."""
    role = get_role()
    if role not in allowed:
        raise err_forbidden()
    return role


def get_user_id():
    return request.headers.get("X-User-ID")
