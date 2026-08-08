"""Authentication (ladder step 1) and authorization (ladder step 2)."""

from flask import g, request

from errors import ApiError

ROLES = ("Anonymous", "Operator", "Inspector", "PlanReviewer", "HealthAuthorityAdmin")


def authenticate():
    """Ladder step 1.  Populates g.role / g.user_id."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role.strip() == "" or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is missing or unrecognised.")
    if role != "Anonymous":
        if user_id is None or user_id.strip() == "":
            raise ApiError("ERR_UNAUTHENTICATED",
                           "X-User-ID is required for role %s." % role)
    g.role = role
    g.user_id = user_id if role != "Anonymous" else (user_id or None)
    return role, g.user_id


def authorize(*allowed_roles):
    """Ladder step 2."""
    if g.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s may not call this endpoint." % g.role)


def require_action_role(action, mapping):
    """Role-per-action authorization for multi-actor transition endpoints."""
    allowed = mapping.get(action)
    if allowed is None:
        return
    if g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s may not perform action %s." % (g.role, action))


def is_operator():
    return g.role == "Operator"


def acting_user_id():
    return getattr(g, "user_id", None)


def own_or_403(owner_operator_id):
    """Ladder step 10 — ownership only constrains the Operator role."""
    if g.role == "Operator" and owner_operator_id != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "This resource belongs to another operator.")
