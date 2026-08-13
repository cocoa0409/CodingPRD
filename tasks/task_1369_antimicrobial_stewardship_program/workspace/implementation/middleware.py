"""Auth context extraction and role authorization (PRD 2.1).

Headers: X-User-ID (actor id) and X-User-Role (one of six roles).
StewardshipAdmin identity is opaque; entity-backed roles carry a Practitioner id
in X-User-ID but the id is only dereferenced where a workflow references a
practitioner (ownership / segregation checks use the body-supplied actor ids
exactly as narrated in PRD section 3).
"""

from flask import request

from errors import err_missing_user_context, err_insufficient_permissions

ROLES = {
    "StewardshipAdmin",
    "StewardshipDirector",
    "IDPharmacist",
    "AttendingPhysician",
    "Microbiologist",
    "InfectionPreventionist",
}

ALL_ROLES = sorted(ROLES)


def auth_context():
    """Validate presence of both headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip():
        raise err_missing_user_context()
    if role is None or not role.strip():
        raise err_missing_user_context()
    role = role.strip()
    if role not in ROLES:
        raise err_insufficient_permissions("Unrecognized role")
    return user_id.strip(), role


def require_role(role: str, allowed):
    if role not in allowed:
        raise err_insufficient_permissions()
