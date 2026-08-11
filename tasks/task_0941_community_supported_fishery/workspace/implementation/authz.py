"""Screening-ladder rungs 1, 2, 3 and 22 (PRD 2.1, 2.5)."""
from flask import g, request

from constants import ALL_ROLES, ROLE_MEMBER, ROLE_VENDOR
from errors import ApiError


def authenticate():
    """Rungs 1 and 2 -- headers present, non-empty, and naming a declared role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def require_roles(*roles):
    """Rung 3 -- the acting role appears in the endpoint's authorised list."""
    authenticate()
    if g.role not in roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return g.role


def is_member():
    return g.role == ROLE_MEMBER


def is_vendor():
    return g.role == ROLE_VENDOR


def own_member(member_id):
    """Rung 22 for a Member actor."""
    if is_member() and g.user_id != member_id:
        raise ApiError("ERR_UNAUTHORIZED")


def own_vessel(vessel_id):
    """Rung 22 for a Vendor actor."""
    if is_vendor() and g.user_id != vessel_id:
        raise ApiError("ERR_UNAUTHORIZED")


def own_member_any(member_ids):
    """Rung 22 where either side of a two-party resource confers ownership."""
    if is_member() and g.user_id not in member_ids:
        raise ApiError("ERR_UNAUTHORIZED")
