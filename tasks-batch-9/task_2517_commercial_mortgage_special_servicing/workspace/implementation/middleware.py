"""Authentication, RBAC and ownership (PRD section 2.1).

Every request — reads included — must carry X-User-ID and X-User-Role.
"""
from flask import g, request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

MASTER_SERVICER = "MasterServicer"
ASSET_MANAGER = "SpecialServicerAssetManager"
COMMITTEE = "SpecialServicingCommitteeOfficer"
CCR = "ControllingClassRepresentative"
BORROWER = "Borrower"
TRUSTEE = "Trustee"
PLATFORM_ADMIN = "PlatformAdmin"

ROLES = (
    MASTER_SERVICER,
    ASSET_MANAGER,
    COMMITTEE,
    CCR,
    BORROWER,
    TRUSTEE,
    PLATFORM_ADMIN,
)

# Convenience bundles used by the route modules.
ALL_STAFF = (MASTER_SERVICER, ASSET_MANAGER, COMMITTEE, TRUSTEE, PLATFORM_ADMIN)
STAFF_PLUS_CCR = (MASTER_SERVICER, ASSET_MANAGER, COMMITTEE, CCR, TRUSTEE, PLATFORM_ADMIN)
STAFF_PLUS_BORROWER = (MASTER_SERVICER, ASSET_MANAGER, COMMITTEE, BORROWER, TRUSTEE, PLATFORM_ADMIN)


def authenticate(allowed_roles):
    """Rule 1 then rule 2 of the refusal precedence (PRD section 2.8)."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles is not None and role not in tuple(allowed_roles):
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def actor():
    return g.user_id, g.user_role


def user_id():
    return g.user_id


def role():
    return g.user_role


def require_owner(expected_key):
    """Rule 4: an entity-backed caller's X-User-ID must equal the owning key."""
    if g.user_role in (BORROWER, CCR):
        if expected_key is None or str(expected_key) != g.user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
