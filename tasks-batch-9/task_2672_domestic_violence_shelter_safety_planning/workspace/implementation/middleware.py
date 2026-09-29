"""Authentication (X-User-ID / X-User-Role) and role authorisation (PRD 2.1)."""

from flask import request

from errors import ApiError

ROLE_HOTLINE_ADVOCATE = "HotlineAdvocate"
ROLE_SHELTER_MANAGER = "ShelterManager"
ROLE_LEGAL_ADVOCATE = "LegalAdvocate"
ROLE_HOUSING_SPECIALIST = "HousingSpecialist"
ROLE_PRIVACY_OFFICER = "PrivacyOfficer"
ROLE_AGENCY_ADMIN = "AgencyAdmin"

ALL_ROLES = (
    ROLE_HOTLINE_ADVOCATE,
    ROLE_SHELTER_MANAGER,
    ROLE_LEGAL_ADVOCATE,
    ROLE_HOUSING_SPECIALIST,
    ROLE_PRIVACY_OFFICER,
    ROLE_AGENCY_ADMIN,
)

# Roles whose X-User-ID is the id of the acting StaffMember.  AgencyAdmin is an
# opaque operator identifier and never satisfies an ownership comparison.
ENTITY_BACKED_ROLES = (
    ROLE_HOTLINE_ADVOCATE,
    ROLE_SHELTER_MANAGER,
    ROLE_LEGAL_ADVOCATE,
    ROLE_HOUSING_SPECIALIST,
    ROLE_PRIVACY_OFFICER,
)


def auth(allowed_roles):
    """Authenticate then authorise; authorisation never precedes authentication."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


def acting_staff_id(user_id, role):
    """The StaffMember id the caller is acting as, or None for the opaque admin."""
    if role in ENTITY_BACKED_ROLES:
        return user_id
    return None
