"""Auth header extraction and role checking per scaffold validations priority 1-2."""

from flask import request
from errors import ApiError

VALID_ROLES = {"PlatformAdmin", "CommodityAdvisor", "Grower", "ComplianceOfficer"}


def get_auth():
    """Return (user_id, role). Raise 401 if headers missing or role unknown."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "Missing or unknown X-User-Role / X-User-ID headers",
            401,
        )
    return user_id, role


def require_role(role, allowed):
    """allowed: iterable of role names. Raise 403 ERR_FORBIDDEN_ROLE."""
    if role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "Authenticated role is not listed on the endpoint",
            403,
        )


def check_grower_ownership(user_id, role, operation_id):
    """For entity_backed Grower calls: X-User-ID must equal owning operation id."""
    if role == "Grower" and user_id != operation_id:
        raise ApiError(
            "ERR_RESOURCE_NOT_OWNED",
            "Grower X-User-ID does not equal the operation id owning the target resource",
            403,
        )
