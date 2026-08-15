from types import SimpleNamespace

from flask import request

from db import STORE
from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {"SecurityAdmin", "SecurityOfficer", "FrontDesk", "Resident", "Vendor"}
ENTITY_BACKED = {"Resident", "Vendor"}


def authenticate():
    """Priority 1: X-User-Role and X-User-ID present; role recognized; for
    entity_backed roles the id must resolve to a Person."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Missing X-User-ID or X-User-Role header")
    if role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Unrecognized role: %s" % role)
    person = None
    if role in ENTITY_BACKED:
        person = STORE["persons"].get(user_id)
        if person is None:
            raise ApiError(ERR_UNAUTHENTICATED, 401,
                           "Entity-backed role id does not resolve to a Person")
    return SimpleNamespace(user_id=user_id, role=role, person=person)


def require_roles(ctx, roles):
    """Priority 2 (role permission)."""
    if ctx.role not in roles:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "Role %s not permitted for this endpoint" % ctx.role)


def body():
    """JSON request body as a dict; non-dict / absent bodies become {}."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}
