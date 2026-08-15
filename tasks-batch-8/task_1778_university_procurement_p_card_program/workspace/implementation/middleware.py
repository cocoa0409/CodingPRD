"""Auth middleware: identity headers (p1) and role authorization (p2).

PRD 2.1: every request carries X-User-ID and X-User-Role. When the role is
Cardholder, X-User-ID is the acting PCard's id; for all other roles it is an
opaque operator identifier.
"""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
)

ROLES = [
    "Requester",
    "DepartmentApprover",
    "Buyer",
    "ProcurementDirector",
    "ContractOfficer",
    "GrantOfficer",
    "APClerk",
    "ReceivingClerk",
    "Cardholder",
    "SurplusManager",
    "ProcurementAdmin",
]
ROLE_SET = set(ROLES)


def authenticate(allowed_roles):
    """Priority 1 (user context headers) then priority 2 (role authorization).

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or not str(user_id).strip()
        or role is None
        or not str(role).strip()
        or role not in ROLE_SET
    ):
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and the role must be a declared role",
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            403,
            f"role {role} is not authorized for this endpoint",
        )
    return user_id, role
