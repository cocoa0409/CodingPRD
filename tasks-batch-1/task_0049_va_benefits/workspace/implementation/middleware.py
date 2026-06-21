from flask import request
import errors
from errors import err

# The system recognizes exactly four roles, spelled precisely (PRD §2.1).
RECOGNIZED_ROLES = {"ClaimsAdmin", "RatingSpecialist", "SchoolCertifyingOfficial", "Veteran"}


def authenticate():
    """Validation priority 1 (PRD §2.1 / §3.15).

    Every request must carry X-User-ID and X-User-Role. If either header is
    missing, or X-User-Role is not one of the four declared roles, reject with
    ERR_UNAUTHENTICATED. Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in RECOGNIZED_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers.")
    return user_id, role


def require_role(role, allowed):
    """Validation priority 2 (PRD §2.1 / §3.15): the acting role must be
    permitted for this operation."""
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN, "Role not permitted for this operation.")


def require_veteran_owner(role, user_id, veteran_id):
    """Validation priority 2 (PRD §2.1): the Veteran self-service role may only
    act on resources whose veteran_id (or, for the veteran's own record, id)
    equals X-User-ID.

    Only the entity-backed Veteran role undergoes this check; the three opaque
    operator roles (ClaimsAdmin, RatingSpecialist, SchoolCertifyingOfficial)
    never compare X-User-ID to any entity. An ownership mismatch surfaces as
    ERR_FORBIDDEN (it is part of the permission check, not a not-found).
    """
    if role == "Veteran" and user_id != veteran_id:
        raise err(errors.ERR_FORBIDDEN, "Veteran may only act on their own resources.")
