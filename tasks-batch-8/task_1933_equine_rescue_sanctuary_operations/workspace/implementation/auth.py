"""Authentication and role authorization (PRD 2.1, cascade tiers 1-3)."""

from flask import request

import db
from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLE_SANCTUARY_DIRECTOR = "SanctuaryDirector"
ROLE_INTAKE_COORDINATOR = "IntakeCoordinator"
ROLE_VETERINARIAN = "Veterinarian"
ROLE_FARRIER = "Farrier"
ROLE_ADOPTION_OFFICER = "AdoptionOfficer"
ROLE_ADOPTER = "Adopter"
ROLE_SPONSOR = "Sponsor"
ROLE_BARN_MANAGER = "BarnManager"
ROLE_VOLUNTEER_COORDINATOR = "VolunteerCoordinator"
ROLE_VOLUNTEER = "Volunteer"

DECLARED_ROLES = {
    ROLE_SANCTUARY_DIRECTOR,
    ROLE_INTAKE_COORDINATOR,
    ROLE_VETERINARIAN,
    ROLE_FARRIER,
    ROLE_ADOPTION_OFFICER,
    ROLE_ADOPTER,
    ROLE_SPONSOR,
    ROLE_BARN_MANAGER,
    ROLE_VOLUNTEER_COORDINATOR,
    ROLE_VOLUNTEER,
}

# Identity-establishing endpoints: X-User-ID is not resolved on these.
REGISTRATION_PATHS = {
    ("POST", "/rescue-ops/adopters"),
    ("POST", "/rescue-ops/sponsors"),
    ("POST", "/rescue-ops/volunteers"),
}


def authenticate(allowed_roles):
    """Run cascade tiers 1-3. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or unknown X-User-Role / X-User-ID headers")

    # Tier 2: entity-backed identity resolution (registration endpoints exempt).
    if (request.method, request.path) not in REGISTRATION_PATHS:
        if role == ROLE_ADOPTER and user_id not in db.adopters:
            raise_err(ERR_FORBIDDEN, "X-User-ID is not an existing Adopter")
        if role == ROLE_SPONSOR and user_id not in db.sponsors:
            raise_err(ERR_FORBIDDEN, "X-User-ID is not an existing Sponsor")
        if role == ROLE_VOLUNTEER and user_id not in db.volunteers:
            raise_err(ERR_FORBIDDEN, "X-User-ID is not an existing Volunteer")
        if role == ROLE_VETERINARIAN:
            p = db.practitioners.get(user_id)
            if p is None or p["specialty"] != "VETERINARIAN":
                raise_err(ERR_FORBIDDEN, "X-User-ID is not a VETERINARIAN Practitioner")
        if role == ROLE_FARRIER:
            p = db.practitioners.get(user_id)
            if p is None or p["specialty"] != "FARRIER":
                raise_err(ERR_FORBIDDEN, "X-User-ID is not a FARRIER Practitioner")

    # Tier 3: role authorization.
    if role not in allowed_roles:
        raise_err(ERR_FORBIDDEN, "Role not authorized for this endpoint")
    return user_id, role
