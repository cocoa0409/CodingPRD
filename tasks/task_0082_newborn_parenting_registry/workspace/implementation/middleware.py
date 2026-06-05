"""Auth header extraction and role checking (PRD §2.1).

Every request carries two mandatory headers:
  - X-User-ID:   opaque operator identifier (never matched against any entity)
  - X-User-Role: one of the six recognized roles

Missing header or unknown role => ERR_UNAUTHENTICATED (401).
Known role not permitted for the operation => ERR_UNAUTHORIZED (403).
Authorization is purely role-based; X-User-ID is never used for ownership.
"""

from flask import g, request

from errors import unauthenticated, unauthorized

VALID_ROLES = {
    "IntakeClerk",
    "AttendingNurse",
    "Neonatologist",
    "BenefitsCoordinator",
    "VitalRecordsOfficer",
    "RegistrySupervisor",
}


def extract_identity():
    """Parse and validate the two auth headers; raise ERR_UNAUTHENTICATED if
    a header is missing or the role is not one the system recognizes."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise unauthenticated()
    if role not in VALID_ROLES:
        raise unauthenticated(f"Unknown role: {role!r}.")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(*allowed):
    """Raise ERR_UNAUTHORIZED unless the caller's role is one of `allowed`."""
    if g.user_role not in allowed:
        raise unauthorized(
            f"Role {g.user_role!r} is not authorized for this operation."
        )
