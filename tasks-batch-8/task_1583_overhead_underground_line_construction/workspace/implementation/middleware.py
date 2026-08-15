"""Auth: X-User-Role header validation and per-endpoint role checks (PRD 2.1).

X-User-ID is opaque for every role: recorded nowhere, never compared against
any resource field. Only X-User-Role gates access.
"""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ALL_ROLES = [
    "CONTRACTOR_PM",
    "FOREMAN",
    "UTILITY_INSPECTOR",
    "UTILITY_DISPATCHER",
    "SAFETY_OFFICER",
]


def get_role() -> str:
    """Priority 1: X-User-Role present and one of the five declared roles."""
    role = request.headers.get("X-User-Role", "").strip()
    if not role or role not in ALL_ROLES:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-Role header must be present and name a declared role")
    return role


def authorized(allowed_roles) -> str:
    """Priorities 1-2: authentication, then role membership for the endpoint."""
    role = get_role()
    if role not in allowed_roles:
        raise_error(ERR_FORBIDDEN,
                    f"role {role} is not authorized for this endpoint")
    return role
