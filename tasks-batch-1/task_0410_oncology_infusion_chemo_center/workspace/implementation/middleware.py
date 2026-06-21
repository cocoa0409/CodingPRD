"""Auth header extraction and RBAC enforcement."""
from flask import request

import errors
from errors import err

VALID_ROLES = {"Pharmacist", "Nurse", "PriorAuthCoordinator"}


def get_auth():
    """Validate X-User-ID and X-User-Role; return (user_id, role).

    Missing or malformed (empty / unknown role) -> ERR_MISSING_AUTH (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err(errors.ERR_MISSING_AUTH, "Missing X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise err(errors.ERR_MISSING_AUTH, "Malformed X-User-ID header")
    if not isinstance(role, str) or role.strip() == "":
        raise err(errors.ERR_MISSING_AUTH, "Malformed X-User-Role header")
    if role not in VALID_ROLES:
        raise err(errors.ERR_MISSING_AUTH, "Unrecognized X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    """Ensure the acting role is in the allowed set, else ERR_FORBIDDEN_ROLE (403)."""
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this operation" % role)
