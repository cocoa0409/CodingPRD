"""Auth header extraction and role checks (PRD section 2.1)."""
from flask import request

from errors import (
    ERR_MISSING_USER_CONTEXT,
    ERR_FORBIDDEN_ROLE,
    raise_err,
)

ROLES = {"Principal", "Consultant", "Reviewer", "FieldTechnician", "ManufacturerRep"}
ANY_ROLE = frozenset(ROLES)


def auth():
    """Validation tier 1: X-User-ID and X-User-Role must be present, non-empty."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or not role.strip():
        raise_err(
            ERR_MISSING_USER_CONTEXT,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    return uid, role


def require_role(role, allowed):
    """Validation tier 2: role must be permitted for this endpoint."""
    if role not in allowed:
        raise_err(
            ERR_FORBIDDEN_ROLE,
            f"Role '{role}' is not permitted for this endpoint",
        )
