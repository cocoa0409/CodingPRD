"""Auth header extraction and RBAC enforcement (PRD §2.1, §1.7)."""
from flask import request

import errors

# The four known roles, spelled exactly as in PRD §2.1.
KNOWN_ROLES = {"OpsAdmin", "GateController", "RampAgent", "SlotCoordinator"}

# Header names from PRD §2.1.
HDR_USER_ID = "X-User-ID"
HDR_USER_ROLE = "X-User-Role"


def authenticate():
    """Validate the two mandatory auth headers (priority 1).

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED if either header is
    missing or the role is not one of the four known roles.
    """
    user_id = request.headers.get(HDR_USER_ID)
    role = request.headers.get(HDR_USER_ROLE)
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(role, allowed):
    """RBAC check (priority 2). Raise ERR_FORBIDDEN_ROLE when role not allowed."""
    if role not in allowed:
        raise errors.forbidden()
