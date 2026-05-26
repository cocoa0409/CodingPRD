"""Auth header extraction and RBAC helpers. PRD §2.1 / §2.9 validation order."""
from flask import request

from errors import unauthenticated, forbidden


ROLE_PLANNER = "SchedulingPlanner"
ROLE_OPS = "OperationsController"
ROLE_CREW = "CrewMember"

VALID_ROLES = {ROLE_PLANNER, ROLE_OPS, ROLE_CREW}


def read_auth():
    """Priority 1 (PRD §2.9): both X-User-ID and X-User-Role headers must be
    present and non-empty. Otherwise ERR_UNAUTHENTICATED (HTTP 401)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise unauthenticated("X-User-ID and X-User-Role headers required")
    return user_id.strip(), role.strip()


def require_roles(allowed):
    """Priority 2 (PRD §2.9): role must be in the endpoint's allowed list.
    Returns (user_id, role) for downstream use. Raises ERR_FORBIDDEN otherwise.
    """
    user_id, role = read_auth()
    if role not in allowed:
        raise forbidden(f"Role {role!r} not authorized for this endpoint")
    return user_id, role
