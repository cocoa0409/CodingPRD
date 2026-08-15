"""Auth: X-User-ID / X-User-Role header extraction and role gating.

Roles (exact spellings): CoopAdmin, GrowerMember, FieldOfficer,
StationOperator, PoolManager. GrowerMember and StationOperator are
entity-backed: their X-User-ID is the id of a Member / ReceivingStation.
"""
from flask import g, request

from errors import ApiError

ROLES = ["CoopAdmin", "GrowerMember", "FieldOfficer", "StationOperator", "PoolManager"]

ANY_ROLE = set(ROLES)


def authenticate():
    """Validate the two auth headers; returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID and X-User-Role headers are required and role must be declared")
    g.user_id = uid
    g.user_role = role
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Role %s is not permitted on this endpoint" % role)


def forbidden(message="Ownership or role check failed"):
    raise ApiError("ERR_FORBIDDEN", 403, message)
