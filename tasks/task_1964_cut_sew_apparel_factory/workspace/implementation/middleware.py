"""Auth header extraction and role checking (PRD §2.1).

Every request carries X-User-ID and X-User-Role. The nine declared roles are
listed below; `Any` is a pseudo-role used only in the docs to mark read
endpoints — it is NOT a valid header value. SewingOperator identity is
entity-backed: X-User-ID is the acting Operator's id. All other roles are
opaque.
"""

from flask import request

from errors import missing_context, forbidden_role

ROLE_MERCHANDISER = "Merchandiser"
ROLE_MATERIALS_PLANNER = "MaterialsPlanner"
ROLE_CUTTING_MANAGER = "CuttingManager"
ROLE_PRODUCTION_PLANNER = "ProductionPlanner"
ROLE_LINE_SUPERVISOR = "LineSupervisor"
ROLE_SEWING_OPERATOR = "SewingOperator"
ROLE_QUALITY_INSPECTOR = "QualityInspector"
ROLE_PAYROLL_CLERK = "PayrollClerk"
ROLE_PLANT_MANAGER = "PlantManager"

ALL_ROLES = [
    ROLE_MERCHANDISER,
    ROLE_MATERIALS_PLANNER,
    ROLE_CUTTING_MANAGER,
    ROLE_PRODUCTION_PLANNER,
    ROLE_LINE_SUPERVISOR,
    ROLE_SEWING_OPERATOR,
    ROLE_QUALITY_INSPECTOR,
    ROLE_PAYROLL_CLERK,
    ROLE_PLANT_MANAGER,
]

ROLES = set(ALL_ROLES)


def authenticate():
    """Validate the two auth headers; return (role, user_id)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise missing_context(
            "X-User-ID and X-User-Role headers are required and X-User-Role "
            "must be one of the declared roles"
        )
    return role, user_id


def require_roles(allowed):
    role, user_id = authenticate()
    if role not in allowed:
        raise forbidden_role(f"role {role} is not authorized for this endpoint")
    return role, user_id
