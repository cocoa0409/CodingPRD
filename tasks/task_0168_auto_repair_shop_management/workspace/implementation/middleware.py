"""Auth header extraction and role checking (PRD 2.1, 2.6).

Every request must carry X-User-ID and X-User-Role. Missing/malformed -> 400
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER. Role not permitted for the endpoint
-> 403 ERR_FORBIDDEN_FOR_ROLE. (Validation order per PRD 2.6.)
"""
from flask import request

from errors import ApiError

VALID_ROLES = {"ServiceAdvisor", "Technician", "Customer", "PartsManager", "ShopManager"}


def get_user_context():
    """Validate and return (user_id, role). Raises on missing/malformed header.

    This is the first gate (PRD 2.6 priority 1).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required.",
        )
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be non-empty.",
        )
    if role not in VALID_ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-Role is not a recognized role.",
        )
    return user_id, role


def require_role(role, allowed):
    """Enforce RBAC: role must be in `allowed`.

    ShopManager is the operational superset and may perform any operation
    reserved to ServiceAdvisor / Technician / PartsManager as an override
    (PRD 2.1). We therefore include ShopManager implicitly whenever any of
    those three is allowed — but ShopManager is NOT granted Customer-exclusive
    operations (authorize / decision), which require entity-backed ownership.
    """
    if role in allowed:
        return
    if role == "ShopManager" and (
        "ServiceAdvisor" in allowed
        or "Technician" in allowed
        or "PartsManager" in allowed
        or "ShopManager" in allowed
    ):
        return
    raise ApiError(
        "ERR_FORBIDDEN_FOR_ROLE",
        "Your role is not permitted to perform this operation.",
    )
