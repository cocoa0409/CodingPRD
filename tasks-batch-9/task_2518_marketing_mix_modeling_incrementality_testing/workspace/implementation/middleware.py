"""Authentication and RBAC (PRD section 2.1)."""

from flask import request

from errors import ApiError

DATA_ENGINEER = "DataEngineer"
MODELER = "Modeler"
EXPERIMENT_DESIGNER = "ExperimentDesigner"
ANALYTICS_LEAD = "AnalyticsLead"
BRAND_PLANNER = "BrandPlanner"
AUDITOR = "Auditor"

ALL_ROLES = (
    DATA_ENGINEER,
    MODELER,
    EXPERIMENT_DESIGNER,
    ANALYTICS_LEAD,
    BRAND_PLANNER,
    AUDITOR,
)

# The five non-Auditor roles may drive the logical clock.
WRITER_ROLES = (
    DATA_ENGINEER,
    MODELER,
    EXPERIMENT_DESIGNER,
    ANALYTICS_LEAD,
    BRAND_PLANNER,
)

# Every role may issue every read operation under /mmm.
READ_ROLES = ALL_ROLES


def authenticate(allowed_roles):
    """Validate the identity headers and the caller's role. Returns the user id."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHORIZED", "Unknown role '%s'." % role)
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role '%s' may not perform this operation." % role)
    return str(user_id).strip()
