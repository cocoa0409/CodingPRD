"""Authentication and role authorization (PRD 2.1, ladder rungs 1-2)."""

from flask import g, request

from errors import ApiError

ROLES = (
    "AccreditationDirector",
    "StandardOwner",
    "EvidenceValidator",
    "TracerSurveyor",
    "SafetyOfficer",
    "UnitManager",
    "ExternalSurveyor",
)

ALL_ROLES = ROLES


def authenticate():
    """Rung 1: X-User-ID and X-User-Role present, role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = str(user_id)
    g.role = role
    return g.user_id, g.role


def require_roles(*roles):
    """Rung 1 then rung 2 (endpoint-level role check)."""
    user_id, role = authenticate()
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


def require_action_role(role, action, action_roles):
    """Rung 2 for multi-action endpoints: the acting role must be permitted for
    the specific action requested."""
    allowed = action_roles.get(action)
    if allowed is not None and role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")
