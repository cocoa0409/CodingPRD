"""Auth header extraction and RBAC (PRD 2.1, ladder stages 1-3)."""

from flask import request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_FIRM_ADMIN = "FirmAdmin"
ROLE_SCHEDULING_MANAGER = "SchedulingManager"
ROLE_ENGAGEMENT_PARTNER = "EngagementPartner"
ROLE_ENGAGEMENT_STAFF = "EngagementStaff"
ROLE_INDEPENDENCE_OFFICER = "IndependenceOfficer"

ROLES = (
    ROLE_FIRM_ADMIN,
    ROLE_SCHEDULING_MANAGER,
    ROLE_ENGAGEMENT_PARTNER,
    ROLE_ENGAGEMENT_STAFF,
    ROLE_INDEPENDENCE_OFFICER,
)


def authorize(*allowed_roles):
    """Run ladder stages 1-3 and return (user_id, role)."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip() or not role or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_INVALID_ROLE", "Role '%s' is not recognised." % role)
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role '%s' may not call this endpoint." % role)
    return user_id, role
