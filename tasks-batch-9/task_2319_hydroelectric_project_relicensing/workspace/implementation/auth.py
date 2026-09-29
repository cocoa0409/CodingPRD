"""Authentication, role gating and project-scoped party resolution (PRD 2.1, 2.12)."""
from flask import g, request

from constants import ALL_ROLES
from db import db
from errors import ApiError

ENTITY_BACKED_ROLES = ("AgencyReviewer", "Stakeholder")
PARTY_TYPES_BY_ROLE = {
    "AgencyReviewer": ("AGENCY",),
    "Stakeholder": ("TRIBE", "NGO"),
}


def _parties_for_user(user_id):
    matches = [p for p in db.parties.values() if p.get("contact_user_id") == user_id]
    matches.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return matches


def authenticate(roles, clock_endpoint=False):
    """Ladder rungs 1 and 2.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if not clock_endpoint:
        if user_id is None or not str(user_id).strip():
            raise ApiError("ERR_UNAUTHORIZED", "X-User-ID header is required.")
        if role in ENTITY_BACKED_ROLES:
            candidates = _parties_for_user(user_id)
            if not candidates:
                raise ApiError("ERR_UNAUTHORIZED", "X-User-ID does not name a known user.")
            g.party_candidates = candidates
            g.party = candidates[0]
        else:
            g.party_candidates = []
            g.party = None
    else:
        g.party_candidates = []
        g.party = None

    if role is None or role not in ALL_ROLES or role not in roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", "Role is not permitted on this endpoint.")

    if not clock_endpoint and role in ENTITY_BACKED_ROLES:
        allowed = [
            p
            for p in g.party_candidates
            if p["party_type"] in PARTY_TYPES_BY_ROLE[role]
        ]
        if not allowed:
            raise ApiError(
                "ERR_ROLE_NOT_PERMITTED",
                "Acting party type does not match the declared role.",
            )
        g.party_candidates = allowed
        g.party = allowed[0]

    g.user_id = user_id
    g.role = role
    return user_id, role


def acting_party():
    return getattr(g, "party", None)


def require_project_scope(project_id):
    """Ladder rung 3: entity-backed roles must belong to the target project."""
    role = getattr(g, "role", None)
    if role not in ENTITY_BACKED_ROLES:
        return
    on_project = [
        p for p in getattr(g, "party_candidates", []) if p["project_id"] == project_id
    ]
    if not on_project:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Acting party is not registered on the target project.",
        )
    g.party = on_project[0]
