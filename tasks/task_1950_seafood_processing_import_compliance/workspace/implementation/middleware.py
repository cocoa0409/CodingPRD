"""Auth: X-User-ID / X-User-Role headers (PRD §2.1, validations priority 1-2)."""
from functools import wraps

from flask import g, request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE

ROLE_IMPORT_COORDINATOR = "ImportCoordinator"
ROLE_RECEIVING_INSPECTOR = "ReceivingInspector"
ROLE_QA_TECH = "QualityAssuranceTech"
ROLE_PROCESSING_SUPERVISOR = "ProcessingSupervisor"
ROLE_COMPLIANCE_MANAGER = "ComplianceManager"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = {
    ROLE_IMPORT_COORDINATOR,
    ROLE_RECEIVING_INSPECTOR,
    ROLE_QA_TECH,
    ROLE_PROCESSING_SUPERVISOR,
    ROLE_COMPLIANCE_MANAGER,
    ROLE_PLATFORM_ADMIN,
}

# "Any" on GET endpoints = the five operational roles (PlatformAdmin has no
# shared operations per the RBAC matrix).
ANY_OPERATIONAL = (
    ROLE_IMPORT_COORDINATOR,
    ROLE_RECEIVING_INSPECTOR,
    ROLE_QA_TECH,
    ROLE_PROCESSING_SUPERVISOR,
    ROLE_COMPLIANCE_MANAGER,
)


def require_roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ALL_ROLES:
                raise ApiError(
                    ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers are required and role must be known",
                    401,
                )
            if role not in allowed:
                raise ApiError(
                    ERR_UNAUTHORIZED_ROLE,
                    "Role %s is not authorized for this operation" % role,
                    403,
                )
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
