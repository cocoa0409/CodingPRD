"""Auth header extraction and role checking.

Per PRD §2.1, every request must carry X-User-ID and X-User-Role.
StudentAthlete role's X-User-ID must equal an existing StudentAthlete.id
(entity-backed). Other roles' X-User-IDs are opaque operator identifiers.
"""

from flask import g, request

import db
from errors import unauthenticated, unauthorized

VALID_ROLES = {
    "ComplianceOfficer",
    "Coach",
    "StudentAthlete",
    "NILReviewer",
    "EligibilityCenter",
}


def extract_identity():
    """Parse X-User-ID and X-User-Role; raise ERR_UNAUTHENTICATED if missing.

    Note: PRD §2.1 says StudentAthlete role's X-User-ID equals an existing
    StudentAthlete.id. We don't validate that here — that becomes an
    ownership check on individual endpoints, because an unknown ID acting
    as StudentAthlete might first need to fail a different existence check.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise unauthenticated()
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(*allowed):
    """Raise ERR_UNAUTHORIZED unless g.user_role is one of `allowed`."""
    if g.user_role not in allowed:
        raise unauthorized(
            f"Role {g.user_role!r} is not authorized for this endpoint."
        )


def is_student_athlete_self(athlete_id: str) -> bool:
    """True if the caller is a StudentAthlete whose X-User-ID equals athlete_id."""
    return g.user_role == "StudentAthlete" and g.user_id == athlete_id
