"""Header authentication and endpoint role authorization (PRD 2.1)."""
from flask import request

from common import ROLES
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def raw_identity():
    return (request.headers.get(USER_ID_HEADER), request.headers.get(USER_ROLE_HEADER))


def authenticate():
    user_id, role = raw_identity()
    if not user_id or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "missing or empty X-User-ID header")
    if not role or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "missing or empty X-User-Role header")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "unrecognized role: %s" % role)
    return user_id, role


def authorize(*allowed):
    """Validation priority 1 then 2 (PRD 2.10)."""
    user_id, role = authenticate()
    if allowed and role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "role %s may not call this endpoint" % role)
    return user_id, role
