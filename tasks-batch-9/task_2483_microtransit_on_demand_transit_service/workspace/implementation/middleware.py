"""Header authentication, role admission, identity resolution and ownership.

Implements steps 1-3 and step 6 of the rejection ladder (PRD Section 2.9).
"""
import functools

from flask import g, request

import db
from errors import ApiError

ROLES = (
    "ZoneAdmin",
    "Dispatcher",
    "Rider",
    "DriverUser",
    "FinanceAnalyst",
    "FundingAgencyAuditor",
)

ALL_ROLES = list(ROLES)


def _authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    if role == "Rider" and user_id not in db.riders:
        raise ApiError("ERR_IDENTITY_NOT_FOUND")
    if role == "DriverUser" and user_id not in db.drivers:
        raise ApiError("ERR_IDENTITY_NOT_FOUND")
    g.user_id = user_id
    g.role = role


def endpoint(roles):
    """Guard a view with the endpoint's authorised role set."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            _authenticate(roles)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def user_id():
    return getattr(g, "user_id", None)


def role():
    return getattr(g, "role", None)


def require_rider_owner(rider_id):
    if role() == "Rider" and rider_id != user_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_driver_owner(driver_id):
    if role() == "DriverUser" and driver_id != user_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
