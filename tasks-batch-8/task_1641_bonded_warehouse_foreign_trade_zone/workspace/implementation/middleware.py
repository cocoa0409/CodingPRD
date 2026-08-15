"""Auth header extraction and endpoint role checks (PRD 2.1, validation priorities 1-2)."""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

ALL_ROLES = {"ZoneOperator", "Importer", "CustomsOfficer", "GateOfficer"}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def authorized(allowed_roles) -> Caller:
    """Priority 1: X-User-ID / X-User-Role present, role declared.
    Priority 2: caller's role listed on the endpoint."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and role must be a declared role",
        )
    if caller_role_not_allowed(role, allowed_roles):
        raise_error(
            ERR_INSUFFICIENT_PERMISSIONS,
            f"role {role} is not authorized for this endpoint",
        )
    return Caller(user_id, role)


def caller_role_not_allowed(role, allowed_roles) -> bool:
    return role not in allowed_roles
