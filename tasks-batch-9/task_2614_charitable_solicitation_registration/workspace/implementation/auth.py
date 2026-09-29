"""Authentication, RBAC and ownership resolution (PRD 2.1, ladder rungs 1/2/6)."""
from functools import wraps

from flask import g, request

from db import db
from errors import ApiError

ROLES = (
    "ComplianceOfficer",
    "CertifyingOfficer",
    "StateRegulator",
    "FundraiserAgent",
    "SystemAdmin",
)

ALL_ROLES = list(ROLES)

# Entity-backed roles: X-User-ID names a persisted row and ownership is checked
# against it.  The other three roles are opaque operator identifiers.
ENTITY_BACKED = {
    "CertifyingOfficer": "OfficerDisclosure",
    "FundraiserAgent": "ProfessionalFundraiser",
}


def authenticate():
    """Ladder rung 1 -- both headers present, non-empty, role among the five."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if not str(user_id).strip() or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(roles):
    """Bind an endpoint's authorized-role list (ladder rungs 1 then 2)."""
    allowed = tuple(roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                raise ApiError("ERR_ROLE_NOT_PERMITTED")
            return view(*args, **kwargs)

        return wrapper

    return decorator


def acting_officer():
    """Resolve the acting CertifyingOfficer to its OfficerDisclosure row.

    PRD 2.1: an X-User-ID under the CertifyingOfficer role that matches no
    OfficerDisclosure at all surfaces as ERR_OFFICER_NOT_FOUND (404), because
    there is no officer to compare ownership against.
    """
    officer = db.officer_disclosures.get(g.user_id)
    if officer is None:
        raise ApiError("ERR_OFFICER_NOT_FOUND")
    return officer


def require_certifying_officer_of(organization_id):
    """Ladder rung 6 for the CertifyingOfficer role.

    The acting X-User-ID must resolve to an OfficerDisclosure of this
    organization whose ``is_certifying_officer`` is true.
    """
    officer = acting_officer()
    if officer["organization_id"] != organization_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if not officer["is_certifying_officer"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return officer


def require_fundraiser_owner(fundraiser_id):
    """Ladder rung 6 for the FundraiserAgent role: X-User-ID equals fundraiser_id."""
    if g.user_id != fundraiser_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return fundraiser_id
