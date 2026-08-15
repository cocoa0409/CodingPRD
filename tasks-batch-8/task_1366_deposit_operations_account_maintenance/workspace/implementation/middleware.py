"""Auth context extraction and role authorization (PRD §2.1, §2.10).

Every request must carry X-User-ID and X-User-Role. Missing headers or an
undeclared role -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400). A role
not permitted on an endpoint -> ERR_FORBIDDEN_FOR_ROLE (403).
"""

from flask import request

from errors import (
    ApiError,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

ROLES = ("OpsOfficer", "OpsManager", "System", "Auditor")

HDR_USER_ID = "X-User-ID"
HDR_USER_ROLE = "X-User-Role"


def get_context():
    """Validation tier 1: user context headers present and role declared."""
    user_id = request.headers.get(HDR_USER_ID)
    role = request.headers.get(HDR_USER_ROLE)
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and the role must be a declared role",
        )
    return user_id, role


def require_roles(allowed_roles):
    """Validation tiers 1+2: returns (user_id, role) after auth and RBAC."""
    user_id, role = get_context()
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            f"Role {role} is not permitted to perform this operation",
        )
    return user_id, role
