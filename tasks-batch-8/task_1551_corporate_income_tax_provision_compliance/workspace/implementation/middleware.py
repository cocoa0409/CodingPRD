"""Auth header extraction and role checks (PRD §2.1, validation priorities 1-2).

Headers: X-User-ID (opaque operator identifier) and X-User-Role (one of the
declared roles). Missing/empty header or undeclared role -> 401
ERR_MISSING_AUTH_CONTEXT; declared role outside the endpoint's role list ->
403 ERR_FORBIDDEN_FOR_ROLE.
"""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_AUTH_CONTEXT,
    ERR_FORBIDDEN_FOR_ROLE,
)

ALL_ROLES = {"TaxAccountant", "TaxManager", "TaxDirector", "Auditor", "PlatformAdmin"}

# Every business read endpoint (PRD §4 GET table).
READER_ROLES = ("TaxAccountant", "TaxManager", "TaxDirector", "Auditor")


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def authorized(allowed_roles) -> Caller:
    """Run validation priorities 1 (auth context) and 2 (role membership)."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(
            ERR_MISSING_AUTH_CONTEXT,
            "X-User-ID and X-User-Role headers must be present and X-User-Role "
            "must be a declared role",
        )
    if role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN_FOR_ROLE,
            f"role {role} is not authorized for this endpoint",
        )
    return Caller(user_id, role)
