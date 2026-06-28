"""Auth header extraction and role checking (§2.1, §2.6)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

VALID_ROLES = {"IntakeCoordinator", "Midwife", "BillingClerk", "CenterAdmin"}


def require_auth():
    """Validate the two mandatory headers (§2.1). Returns (user_id, role).

    Priority 1: both X-User-ID and X-User-Role must be present, else 401.
    The role string itself is checked against the per-endpoint allow-list by
    require_role (priority 2).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: the declared role must be in the operation's allow-list."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this operation" % role)


# Read access (every GET) is open to all four roles (§2.1).
ALL_ROLES = ["IntakeCoordinator", "Midwife", "BillingClerk", "CenterAdmin"]
