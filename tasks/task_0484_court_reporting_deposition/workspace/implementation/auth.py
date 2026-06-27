"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ROLES = {"ScheduleCoordinator", "Reporter", "Attorney", "BillingClerk", "PlatformAdmin"}


def authenticate():
    """Validate the two mandatory headers (PRD §2.1).

    X-User-ID identifies the acting user; X-User-Role declares the role.
    If either header is missing, or X-User-Role is not a recognized role,
    reject with ERR_UNAUTHENTICATED (401).
    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unknown authentication headers.")
    return user_id, role


def require_role(role, allowed):
    """PlatformAdmin is an operational superset (PRD §2.1)."""
    if role == "PlatformAdmin":
        return
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role not permitted for this operation.")
