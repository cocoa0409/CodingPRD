"""Auth header extraction and RBAC (PRD §2.1, SCAFFOLD §1.4 priorities 1-2, §1.7).

Every request carries X-User-ID and X-User-Role. Missing/malformed -> 401
ERR_UNAUTHENTICATED (checked before anything else). Well-formed but not permitted
for the endpoint -> 403 ERR_UNAUTHORIZED.

Six roles, spelled exactly: Admin, IntakeScreener, Investigator, Caseworker,
LicensingWorker, Judge.
"""
from flask import request

import errors

VALID_ROLES = {
    "Admin",
    "IntakeScreener",
    "Investigator",
    "Caseworker",
    "LicensingWorker",
    "Judge",
}

# Map entity-backed role -> the Caseworker.role_type it corresponds to.
ROLE_TO_ROLE_TYPE = {
    "IntakeScreener": "SCREENER",
    "Investigator": "INVESTIGATOR",
    "Caseworker": "CASEWORKER",
    "LicensingWorker": "LICENSING",
}


def authenticate():
    """Validate presence + well-formedness of the two auth headers.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED on missing/malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise errors.unauthenticated()
    if not role or role not in VALID_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def authorize(role, allowed_roles):
    """Raise ERR_UNAUTHORIZED if the acting role is not in allowed_roles."""
    if role not in allowed_roles:
        raise errors.unauthorized()
