"""Auth and RBAC helpers."""
from flask import request
from errors import (
    ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_RESOURCE_OWNER, raise_err
)


VALID_ROLES = {"Parent", "SchoolStaff", "DistrictReviewer", "USDAAuditor", "PlatformAdmin"}


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if role missing/invalid."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in VALID_ROLES:
        raise_err(ERR_UNAUTHENTICATED, "X-User-Role missing or unrecognized")
    # X-User-ID is required to be present even for opaque roles
    if user_id is None or user_id == "":
        raise_err(ERR_UNAUTHENTICATED, "X-User-ID missing")
    return user_id, role


def require_role(allowed_roles):
    """Validate that current request's role is in the allowed list."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise_err(ERR_FORBIDDEN, f"role {role} not permitted")
    return user_id, role


def require_parent_owns(user_id, role, owning_household_id):
    """For Parent role, require X-User-ID == owning_household_id."""
    if role == "Parent" and user_id != owning_household_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this resource")
