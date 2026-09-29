"""Authentication / RBAC (PRD §2.1, §2.6 bands 1-2)."""
from flask import request

from errors import fail

ROLE_PLANNER = "PortOperationsPlanner"
ROLE_SURVEYOR = "DamageSurveyor"
ROLE_TECH = "AccessoryTechnician"
ROLE_INSPECTOR = "QualityInspector"
ROLE_MANAGER = "DistributionManager"
ROLE_DEALER = "Dealer"

ALL_ROLES = [
    ROLE_PLANNER,
    ROLE_SURVEYOR,
    ROLE_TECH,
    ROLE_INSPECTOR,
    ROLE_MANAGER,
    ROLE_DEALER,
]

# Every operator role; the consignee Dealer is excluded.
OPS_ROLES = [ROLE_PLANNER, ROLE_SURVEYOR, ROLE_TECH, ROLE_INSPECTOR, ROLE_MANAGER]


def authenticate(allowed_roles):
    """Returns (user_id, role). 401 on bad headers, 403 on unauthorized role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        fail(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and a valid X-User-Role header are required",
        )
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation" % role)
    return user_id, role
