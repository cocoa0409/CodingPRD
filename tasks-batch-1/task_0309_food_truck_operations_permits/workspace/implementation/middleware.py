"""Auth header extraction and RBAC (PRD §2.1, §3.9)."""

from flask import request

import errors
from errors import err

VALID_ROLES = {"OperatorTruck", "Dispatcher", "HealthInspector", "PlatformAdmin"}


def require_user_context():
    """Validation priority 1: X-User-ID and X-User-Role present and role valid.

    Returns (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT (400)
    when either header is missing/blank or the role is not recognized.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT,
                  "Missing or invalid user context headers")
    return user_id, role


def require_role(role, allowed):
    """Validation priority 2 (role part): acting role must be in `allowed`.

    Raises ERR_FORBIDDEN_ROLE (403) otherwise.
    """
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN_ROLE,
                  "Acting role is not permitted for this operation")


def require_truck_ownership(user_id, role, owning_truck_id):
    """Entity-backed OperatorTruck ownership check (PRD §2.1, §3.9 step 2).

    When the acting role is OperatorTruck, X-User-ID must equal the owning
    truck_id of the target resource. Opaque roles are exempt.
    """
    if role == "OperatorTruck" and user_id != owning_truck_id:
        raise err(errors.ERR_FORBIDDEN_ROLE,
                  "OperatorTruck may only act on resources owned by itself")
