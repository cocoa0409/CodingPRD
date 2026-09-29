"""Header authentication and endpoint authorisation (PRD 2.1, 2.6 steps 1-2)."""
from flask import g, request

from errors import ApiError

ROLES = (
    "PracticeAdministrator",
    "SchedulingCoordinator",
    "BenefitsSpecialist",
    "InventoryManager",
    "Surgeon",
    "AnesthesiaCoordinator",
    "QualityReviewer",
)

# Roles whose X-User-ID names a live StaffMember row and is compared by the
# actor-binding and segregation-of-duties rules.
ENTITY_BACKED_ROLES = ("Surgeon", "AnesthesiaCoordinator", "QualityReviewer")

ROLE_HEADER = "X-User-Role"
USER_HEADER = "X-User-ID"

ALL_ROLES = ROLES


def authorize(*allowed_roles):
    """Authenticate the caller, then authorise the endpoint's role list."""
    role = request.headers.get(ROLE_HEADER)
    user_id = request.headers.get(USER_HEADER)
    if role is not None:
        role = role.strip()
    if user_id is not None:
        user_id = user_id.strip()
        if user_id == "":
            user_id = None

    # Step 1 - header authentication.
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role in ENTITY_BACKED_ROLES and not user_id:
        raise ApiError("ERR_UNAUTHENTICATED")

    # Step 2 - endpoint authorisation.
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")

    g.role = role
    g.user_id = user_id
    return role, user_id


def actor_id():
    return getattr(g, "user_id", None)


def actor_role():
    return getattr(g, "role", None)
