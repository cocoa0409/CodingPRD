"""Auth header extraction and RBAC checks (PRD §2.1, §2.7).

Auth headers (verbatim from PRD §2.1):
  X-User-ID   — acting principal id
  X-User-Role — one of CPOOperator, Driver, StationController

Validation order (PRD §2.7): authentication first (ERR_UNAUTHENTICATED),
then role authorization (ERR_FORBIDDEN). Existence / ownership / body / state /
business checks happen later inside the route handlers.
"""
from flask import request

import errors

ROLES = {"CPOOperator", "Driver", "StationController"}


def get_identity():
    """Return (user_id, role), enforcing presence + known role.

    Raises ERR_UNAUTHENTICATED when either header is missing/blank or the role
    is not one of the three known roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "missing or unknown auth headers")
    return user_id, role


def require_role(role, allowed):
    """Priority-2 role authorization: ERR_FORBIDDEN if role not permitted."""
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN, "role not permitted for this endpoint")
