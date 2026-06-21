"""Auth extraction, RBAC, and request body/validation helpers.

Auth headers (PRD §2.1): X-User-ID and X-User-Role. Roles are exactly
FieldAdjuster, Estimator, ProductionManager. Missing / unknown role -> 401.
Role not permitted for the operation -> 403.
"""
from flask import request

import errors
from errors import ApiError

VALID_ROLES = {"FieldAdjuster", "Estimator", "ProductionManager"}


def get_role():
    """Return the validated role or raise ERR_UNAUTHENTICATED (401)."""
    role = request.headers.get("X-User-Role")
    if not role or role not in VALID_ROLES:
        raise ApiError(errors.ERR_UNAUTHENTICATED, 401,
                       "X-User-Role header missing or not a declared role")
    return role


def get_user_id():
    return request.headers.get("X-User-ID")


def require_role(allowed):
    """Validate auth then check the role is in `allowed`.

    Order matters: 401 (unauthenticated) is checked before 403 (forbidden),
    per PRD §2.9.
    """
    role = get_role()
    if role not in allowed:
        raise ApiError(errors.ERR_FORBIDDEN, 403,
                       "Role not permitted for this operation")
    return role


def get_json_body():
    """Return the parsed JSON body as a dict (empty dict if none/invalid)."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return {}
    return data
