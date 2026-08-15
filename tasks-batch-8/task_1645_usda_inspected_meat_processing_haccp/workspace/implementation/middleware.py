"""Auth header extraction and role checking per PRD §2.1."""

from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ALL_ROLES = {"PlantAdmin", "QAManager", "QATech", "LabAnalyst", "Inspector", "ProductionManager"}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(ERR_UNAUTHENTICATED, "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_roles(*allowed):
    """Validate auth headers, then check the acting role is in the endpoint's role list."""
    user_id, role = get_auth()
    if role not in allowed:
        raise_error(ERR_FORBIDDEN_ROLE, f"Role {role} is not authorized for this endpoint")
    return user_id, role
