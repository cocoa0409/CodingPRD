"""Auth header extraction and role checking.

Headers: X-User-ID and X-User-Role.
Roles: Grower, Agronomist, PlantOperator, LogisticsDispatcher, CreditManager,
       ComplianceOfficer, BranchAdmin.
Grower is entity-backed: X-User-ID is the GrowerAccount id for ownership
checks on grower-scoped resources.
"""

from flask import request, g

from errors import unauthenticated, forbidden

ROLES = {
    "Grower",
    "Agronomist",
    "PlantOperator",
    "LogisticsDispatcher",
    "CreditManager",
    "ComplianceOfficer",
    "BranchAdmin",
}

ALL_ROLES = [
    "Grower",
    "Agronomist",
    "PlantOperator",
    "LogisticsDispatcher",
    "CreditManager",
    "ComplianceOfficer",
    "BranchAdmin",
]


def require_auth():
    """Parse and validate auth headers; populate g.user_id and g.role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise unauthenticated()
    if not role or role not in ROLES:
        raise unauthenticated()
    g.user_id = user_id
    g.role = role


def require_roles(*roles):
    """Check the caller's role is in the allowed set."""
    if g.role not in roles:
        raise forbidden("Role not permitted for this operation")


def check_grower_ownership(grower_id):
    """For Grower-role calls on grower-scoped resources, X-User-ID must equal
    the owning grower's id."""
    if g.role == "Grower" and g.user_id != grower_id:
        raise forbidden("Grower X-User-ID does not own the addressed resource")
