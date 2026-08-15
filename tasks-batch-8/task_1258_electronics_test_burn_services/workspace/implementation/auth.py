"""Authentication and role authorization (PRD §2.1)."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE

ROLES = {"CustomerRep", "TestEngineer", "OperationsManager", "QualityEngineer"}

ALL_ROLES = ("CustomerRep", "TestEngineer", "OperationsManager", "QualityEngineer")


def require_roles(*roles):
    """Validate X-User-ID / X-User-Role, then endpoint role permission."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing or unknown X-User-ID / X-User-Role")
    if role not in roles:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403, f"Role {role} is not permitted here")
    return uid, role
