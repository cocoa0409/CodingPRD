"""Auth header extraction and role checking (PRD §2.1, scaffold §1.4 p1-p2)."""

from flask import request

from errors import missing_auth, forbidden

# Declared role names per PRD §2.1. System is a declared role name but is never
# authorized on any endpoint (it names the actor of automatic transitions only),
# so a request bearing it passes layer 1 and fails layer 2 with 403.
DECLARED_ROLES = {
    "PlatformAdmin",
    "RealEstateAnalyst",
    "RealEstateManager",
    "CommitteeMember",
    "CommitteeChair",
    "ConstructionManager",
    "System",
}

ALL_API_ROLES = (
    "PlatformAdmin",
    "RealEstateAnalyst",
    "RealEstateManager",
    "CommitteeMember",
    "CommitteeChair",
    "ConstructionManager",
)


def require_roles(*allowed):
    """Validate X-User-Role / X-User-ID headers and endpoint authorization.

    Returns (user_id, role) on success; raises ApiError otherwise.
    """
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if (
        role is None
        or not str(role).strip()
        or uid is None
        or not str(uid).strip()
        or role not in DECLARED_ROLES
    ):
        raise missing_auth()
    if role not in allowed:
        raise forbidden()
    return uid, role
