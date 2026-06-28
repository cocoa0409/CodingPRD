"""Auth header extraction + role checking (PRD section 2.1, 2.10)."""
from flask import request

from errors import err

ROLES = {"StudioAdmin", "Instructor", "Parent", "Anonymous"}


def get_identity():
    """Return (user_id, role). Role may be None/invalid -> caller authenticates."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    return user_id, role


def authenticate(allowed_roles):
    """Priority 1 (ERR_UNAUTHENTICATED) then priority 2 (ERR_FORBIDDEN_ROLE).

    allowed_roles: the set of roles permitted for this endpoint.
    Returns (user_id, role).
    """
    user_id, role = get_identity()

    # Priority 1: header present and a recognized role value.
    if role is None or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role.")

    # Anonymous is only ever a real actor where explicitly allowed; everywhere
    # else an Anonymous (or header-less) request is unauthenticated.
    if role == "Anonymous" and "Anonymous" not in allowed_roles:
        raise err("ERR_UNAUTHENTICATED", "Anonymous is not permitted here.")

    # Priority 2: recognized role but not permitted for this endpoint.
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this endpoint.")

    return user_id, role


def require_owner(role, user_id, owning_family_id):
    """Priority 3 (ERR_NOT_RESOURCE_OWNER): Parent acts on own family only.

    StudioAdmin/Instructor/Anonymous are opaque or not ownership-scoped here.
    """
    if role == "Parent":
        if owning_family_id is None or str(user_id) != str(owning_family_id):
            raise err("ERR_NOT_RESOURCE_OWNER",
                      "Parent may only act on their own family's resources.")


def get_json():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body
