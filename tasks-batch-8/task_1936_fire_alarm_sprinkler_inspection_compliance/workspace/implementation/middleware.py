"""Auth header extraction and role checking (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. The three declared roles
are FireMarshal, ContractorAdmin, Technician. For ContractorAdmin, X-User-ID is
the acting Contractor's id; for Technician, the acting Technician's id; for
FireMarshal it is an opaque operator identifier.
"""

from flask import request

from errors import unauthenticated, unauthorized

ROLE_FIRE_MARSHAL = "FireMarshal"
ROLE_CONTRACTOR_ADMIN = "ContractorAdmin"
ROLE_TECHNICIAN = "Technician"

ROLES = {
    ROLE_FIRE_MARSHAL,
    ROLE_CONTRACTOR_ADMIN,
    ROLE_TECHNICIAN,
}

ALL_ROLES = [
    ROLE_FIRE_MARSHAL,
    ROLE_CONTRACTOR_ADMIN,
    ROLE_TECHNICIAN,
]

MARSHAL_AND_ADMIN = [ROLE_FIRE_MARSHAL, ROLE_CONTRACTOR_ADMIN]


def authenticate():
    """Validate the two auth headers; return (role, user_id)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise unauthenticated()
    return role, user_id


def require_roles(allowed):
    role, user_id = authenticate()
    if role not in allowed:
        raise unauthorized()
    return role, user_id
