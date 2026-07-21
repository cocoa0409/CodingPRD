"""Authentication, role authorisation and ownership — PRD §2.1 / §2.8 steps 1-3."""

from flask import request

from errors import ApiError

ROLES = {"PlatformAdmin", "Artist", "Collaborator", "DistributionOps", "FinanceOps", "Fan"}
ENTITY_BACKED = {"Artist", "Collaborator"}


def authenticate():
    """Step 1 — headers present, role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def authorize(role, allowed):
    """Step 2 — role appears in the endpoint's role list."""
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def auth(*allowed_roles):
    """Runs steps 1 and 2; returns (user_id, role)."""
    user_id, role = authenticate()
    authorize(role, allowed_roles)
    return user_id, role


def require_ownership(condition):
    """Step 3 — ERR_FORBIDDEN_OWNERSHIP when the entity-backed caller is not the owner."""
    if not condition:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")


def owns_artist(user_id, role, artist_id):
    """True unless the caller is an Artist acting on somebody else's account."""
    if role != "Artist":
        return True
    return user_id == artist_id


def owns_collaborator(user_id, role, collaborator_id):
    if role != "Collaborator":
        return True
    return user_id == collaborator_id
