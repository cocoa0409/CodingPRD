"""Authentication, role authorisation and resource-ownership checks.

Admission ladder positions 1, 2 and 5 (PRD Section 2.7).
"""
import functools

from flask import g, request

from errors import ApiError

ROLES = ("PlatformAdmin", "SalesRep", "BranchOps", "Driver", "CreditManager", "Customer")

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    """Ladder 1 -- both headers present, role one of the six declared names."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if not str(user_id).strip() or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return str(user_id), role


def endpoint(roles):
    """Bind an endpoint to its authorised-role list (ladder 1 then ladder 2)."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        wrapper.authorized_roles = tuple(roles)
        return wrapper

    return decorator


def require_owns_branch(branch_id):
    """BranchOps X-User-ID is the id of the acting Branch (ladder 5)."""
    if g.role == "BranchOps" and g.user_id != branch_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_owns_truck(truck_id):
    """Driver X-User-ID is the id of the acting Truck (ladder 5)."""
    if g.role == "Driver" and g.user_id != truck_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_owns_customer(customer_id):
    """Customer X-User-ID is the id of the acting Customer record (ladder 5)."""
    if g.role == "Customer" and g.user_id != customer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
