"""Auth header extraction, role checks, and request-body helpers.

Auth headers (PRD §2.1): X-User-ID and X-User-Role.
Recognized roles: AccountManager, Dispatcher, Driver, Inspector, Customer, System.
For Customer, X-User-ID is the acting Account.id (ownership enforced).
"""
from flask import request

import errors

RECOGNIZED_ROLES = {
    "AccountManager",
    "Dispatcher",
    "Driver",
    "Inspector",
    "Customer",
    "System",
}


def require_auth():
    """Validate presence/well-formedness of the user-context headers.

    Returns (user_id, role). Raises ApiError on missing/malformed headers.
    This is validation priority 1 (PRD §2.8).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "Missing X-User-ID or X-User-Role header",
        )
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role or role not in RECOGNIZED_ROLES:
        raise errors.ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "Malformed X-User-ID or X-User-Role header",
        )
    return user_id, role


def require_role(role, allowed):
    """Validation priority 2 (PRD §2.8): role must be permitted for the endpoint."""
    if role not in allowed:
        raise errors.ApiError(
            errors.ERR_FORBIDDEN_FOR_ROLE,
            403,
            "Role %s is not permitted for this operation" % role,
        )


def check_owner(role, user_id, owner_account_id):
    """Validation priority 3 (PRD §2.8): Customer ownership.

    For a Customer acting on an account-scoped resource, X-User-ID must equal
    the resource's owning account_id. Other roles are opaque (no check).
    """
    if role == "Customer" and user_id != owner_account_id:
        raise errors.ApiError(
            errors.ERR_NOT_RESOURCE_OWNER,
            403,
            "Customer does not own the targeted resource",
        )


def get_json_body():
    """Return the parsed JSON body as a dict, or {} when absent/empty.

    A body that is present but not a JSON object is treated as an invalid
    request (ERR_INVALID_REQUEST).
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.ApiError(
            errors.ERR_INVALID_REQUEST, 400, "Request body is not valid JSON"
        )
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.ApiError(
            errors.ERR_INVALID_REQUEST, 400, "Request body must be a JSON object"
        )
    return body
