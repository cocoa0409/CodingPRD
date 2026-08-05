"""Authentication and authorization helpers."""
from flask import request

from errors import ApiError

ROLES = {"PlatformAdmin", "Advisor", "BenefitsCounselor",
         "BillingSpecialist", "CommunityManager", "Family"}


def authenticate():
    """Priority 1: headers present and role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "Missing or invalid authentication headers.")
    return user_id, role


def authorize(role, allowed_roles):
    """Priority 2: acting role is listed for the endpoint."""
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "This role may not call this endpoint.")


def deny_ownership():
    raise ApiError("ERR_UNAUTHORIZED", "This resource is not yours.")


def guard(allowed_roles):
    uid, role = authenticate()
    authorize(role, allowed_roles)
    return uid, role
