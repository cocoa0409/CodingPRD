"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.8, §1.7).

Order of checks (PRD §2.8): (1) authentication, (2) authorization, (3) existence,
(4) body validity, (5) state, then business rules. Auth + role are checked before
any resource lookup."""
from flask import request

import errors

ROLES = {
    "IntakeCoordinator",
    "Pharmacist",
    "AuthSpecialist",
    "VisitingNurse",
    "MedicalDirector",
    "Biller",
    "WarehouseClerk",
}


def get_identity():
    """Returns (user_id, role) after validating both headers are present and
    well-formed. Raises ERR_UNAUTHENTICATED otherwise."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.unauthenticated()
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise errors.unauthenticated()
    if role not in ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require(allowed_roles):
    """Authenticate, then authorize the caller's role against allowed_roles.
    Returns (user_id, role)."""
    user_id, role = get_identity()
    if role not in allowed_roles:
        raise errors.forbidden_role()
    return user_id, role
