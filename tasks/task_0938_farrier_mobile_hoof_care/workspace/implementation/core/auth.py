"""Rungs 1-3: authentication, role authorisation and ownership (PRD 2.1, 2.7).

Both headers are mandatory on EVERY request, including read-only ones.
"""

from flask import g, request

from .constants import ROLES
from .errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ENTITY_BACKED_ROLES = ("Farrier", "ClientUser")


def authenticate(allowed_roles):
    """Run rung 1 then rung 2 and stash the caller on ``g``."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def acting_role():
    return getattr(g, "user_role", None)


def acting_id():
    return getattr(g, "user_id", None)


def require_client_owner(client_id):
    """Rung 3 for the ClientUser role: the resource must belong to the caller."""
    if acting_role() != "ClientUser":
        return
    if client_id is None or client_id != acting_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_farrier_owner(farrier_id):
    """Rung 3 for the Farrier role: the governing route must be the caller's.

    A resource with no governing route (an unrouted appointment, say) has no
    farrier to compare against, so the rung cannot fire for it.
    """
    if acting_role() != "Farrier":
        return
    if farrier_id is None:
        return
    if farrier_id != acting_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
