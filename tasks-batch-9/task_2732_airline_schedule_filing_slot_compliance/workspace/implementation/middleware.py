"""Authentication, role admission and ownership, per PRD sections 2.1 and 2.9 bands 1-2/5."""
from flask import g, request

from errors import ApiError

ROLES = (
    "NetworkPlanner",
    "PartnerCarrier",
    "SlotCoordinator",
    "ComplianceOfficer",
    "FilingAgent",
    "SystemAdmin",
)

ALL_ROLES = ROLES

# The two roles whose X-User-ID is the id of an acting Carrier.
ENTITY_BACKED_ROLES = ("NetworkPlanner", "PartnerCarrier")


def authenticate(allowed_roles):
    """Band 1 then band 2. Returns the acting user id."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not str(user_id).strip() or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    g.user_id = user_id
    g.role = role
    return user_id


def acting_user():
    return getattr(g, "user_id", None)


def acting_role():
    return getattr(g, "role", None)


def require_ownership(owner_carrier_id):
    """Band 5. Only the two entity-backed roles are subject to it."""
    if acting_role() in ENTITY_BACKED_ROLES and acting_user() != owner_carrier_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
