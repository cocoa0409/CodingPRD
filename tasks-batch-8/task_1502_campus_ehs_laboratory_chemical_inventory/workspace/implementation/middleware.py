"""Auth header extraction and role checking (PRD §2.1, scaffold validations 1/3/4)."""
from flask import request

from errors import unauthenticated, forbidden_role

ROLES = ("EHSAdmin", "EHSInspector", "PrincipalInvestigator", "LabMember")


def get_actor():
    """Validate X-User-ID / X-User-Role headers (priority 1).

    Returns (user_id, role). Raises ApiError(ERR_UNAUTHENTICATED) when headers
    are missing/empty or the role is not one of the four declared roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """Priority 3: role authorization for the endpoint."""
    if role not in allowed:
        raise forbidden_role()
