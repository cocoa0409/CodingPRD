"""Auth header extraction and RBAC enforcement (PRD §2.1, §4)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

# The eight peer roles the system recognizes (PRD §2.1).
KNOWN_ROLES = {
    "FacilityAdmin",
    "BoxOfficeOperator",
    "GroupSalesAgent",
    "MembershipClerk",
    "ProgramCoordinator",
    "EventsManager",
    "DevelopmentOfficer",
    "AccessibilityCoordinator",
}


def authenticate():
    """Validate X-User-ID and X-User-Role headers (PRD §2.1).

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED when either header is
    absent or the role is unknown.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED)
    return user_id, role


def require_role(role, allowed):
    """Enforce that `role` is in the `allowed` set (PRD §2.1, §4)."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE)
