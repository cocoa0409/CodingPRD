"""Auth header extraction and role checking."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {"Customer", "StoreClerk", "Grader", "Manager"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if missing/malformed.

    Anonymous access is handled by callers that permit it (they call this only
    when authentication is required).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or not user_id.strip() or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or malformed authentication headers")
    return user_id, role


def get_identity_optional():
    """For endpoints that allow Anonymous. Returns (user_id, role).

    If headers are absent, returns (None, 'Anonymous'). If headers are present
    they must be well-formed for a known role, else ERR_UNAUTHENTICATED.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None and role is None:
        return None, "Anonymous"
    # If either header is present, both must be well-formed.
    if role == "Anonymous":
        if not user_id:
            raise err(ERR_UNAUTHENTICATED, "Missing X-User-ID")
        return user_id, "Anonymous"
    if not user_id or not role or not user_id.strip() or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or malformed authentication headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "Role %s is not permitted for this operation" % role)


def authenticate(allowed_roles):
    """Authenticate and authorize in one call for protected endpoints.

    allowed_roles is a set/list of role names permitted for this operation.
    Returns (user_id, role).
    """
    user_id, role = get_identity()
    require_role(role, allowed_roles)
    return user_id, role
