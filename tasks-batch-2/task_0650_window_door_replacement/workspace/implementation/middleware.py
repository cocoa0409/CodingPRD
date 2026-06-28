"""Authentication and RBAC. Headers: X-User-ID, X-User-Role (PRD §2.1)."""
from flask import request

import errors

ROLES = {"Homeowner", "SalesConsultant", "OperationsCoordinator", "ServiceTech", "PlatformAdmin"}


def get_auth():
    """Validate auth headers presence (priority 1). Returns (user_id, role).

    Raises ERR_UNAUTHENTICATED when either header is missing or empty.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or empty X-User-ID / X-User-Role headers")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: role authorization. Raises ERR_FORBIDDEN_ROLE if not permitted."""
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Role '%s' is not permitted for this operation" % role)
