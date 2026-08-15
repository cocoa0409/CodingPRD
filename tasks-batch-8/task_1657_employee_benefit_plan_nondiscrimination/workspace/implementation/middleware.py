"""Auth header extraction and role checking (PRD §2.1, scaffold §1.7)."""

from flask import request

from errors import unauthenticated, unauthorized

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_PLAN_ADMINISTRATOR = "PlanAdministrator"
ROLE_COMPLIANCE_ANALYST = "ComplianceAnalyst"
ROLE_AUDITOR = "Auditor"

DECLARED_ROLES = {
    ROLE_PLATFORM_ADMIN,
    ROLE_PLAN_ADMINISTRATOR,
    ROLE_COMPLIANCE_ANALYST,
    ROLE_AUDITOR,
}

READ_ROLES = {
    ROLE_PLATFORM_ADMIN,
    ROLE_PLAN_ADMINISTRATOR,
    ROLE_COMPLIANCE_ANALYST,
    ROLE_AUDITOR,
}


def require_roles(allowed):
    """Validate X-User-ID / X-User-Role headers and endpoint role membership.

    Returns the acting user's X-User-ID on success; raises ApiError otherwise.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip():
        raise unauthenticated("X-User-ID header is missing or malformed")
    if role is None or not role.strip():
        raise unauthenticated("X-User-Role header is missing or malformed")
    role = role.strip()
    if role not in DECLARED_ROLES:
        raise unauthenticated("X-User-Role names a role the system does not declare")
    if role not in allowed:
        raise unauthorized("Role %s is not authorized for this endpoint" % role)
    return user_id.strip()
