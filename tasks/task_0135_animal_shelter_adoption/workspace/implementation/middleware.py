"""Auth header extraction and RBAC (PRD §2.1, SCAFFOLD §1.4 / §1.7).

Every request carries X-User-ID and X-User-Role. Missing/malformed -> ERR_UNAUTHENTICATED.
Role not permitted -> ERR_FORBIDDEN. The single exception is the shelter bootstrap
POST /shelters, which may be invoked without an established user context.
"""
from flask import request

import errors

VALID_ROLES = {
    "ShelterAdmin",
    "IntakeOfficer",
    "Veterinarian",
    "AdoptionCounselor",
    "FosterCoordinator",
    "Adopter",
}


def get_identity():
    """Return (user_id, role) from headers, validating presence and role membership.

    Raises ERR_UNAUTHENTICATED if either header is missing/blank or the role is not a
    recognized member.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.unauthenticated()
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise errors.unauthenticated()
    if role not in VALID_ROLES:
        raise errors.unauthenticated("Unknown X-User-Role value")
    return user_id, role


def require(allowed_roles):
    """Authenticate, then enforce that the caller's role is in allowed_roles.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED then ERR_FORBIDDEN in order.
    """
    user_id, role = get_identity()
    if role not in allowed_roles:
        raise errors.forbidden()
    return user_id, role
