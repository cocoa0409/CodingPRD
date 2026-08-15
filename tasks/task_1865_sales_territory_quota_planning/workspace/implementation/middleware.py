"""Auth header extraction and role checking (PRD §2.1, validations tier 1-2)."""
from flask import request
from errors import ApiError

ROLES = ("SalesOpsAdmin", "SalesOpsAnalyst", "RevOpsManager", "SalesRep")


class UserContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_user_context():
    """Tier 1: X-User-ID and X-User-Role must be present and well-formed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID header missing or malformed",
            400,
        )
    if not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-Role header missing or malformed",
            400,
        )
    return UserContext(user_id.strip(), role)


def require_role(ctx, allowed):
    """Tier 2: caller's role must be listed for the endpoint."""
    if ctx.role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_FOR_ROLE",
            f"Role {ctx.role} is not permitted on this endpoint",
            403,
        )
