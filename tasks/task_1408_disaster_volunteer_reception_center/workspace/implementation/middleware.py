"""Auth context extraction and role authorization (PRD sections 2.1, 2.11)."""

from flask import g, request

from errors import (
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED_ROLE,
    raise_error,
)

ALL_ROLES = [
    "VRCManager",
    "IntakeCoordinator",
    "VettingOfficer",
    "LogisticsCoordinator",
    "SiteSupervisor",
    "RiskOfficer",
    "AgencyCoordinator",
    "Volunteer",
]


def authenticate():
    """Pipeline stage 1: header presence and role validity."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and X-User-Role must be a declared role",
        )
    g.user_id = user_id
    g.role = role
    # Per-request mutation registry: each resource is version-bumped at most
    # once per API operation (keyed by python object identity).
    g.touched = set()


def authorize(roles):
    """Pipeline stage 2: role authorization for the endpoint."""
    if g.role not in roles:
        raise_error(
            ERR_UNAUTHORIZED_ROLE,
            f"Role {g.role} is not authorized for this endpoint",
        )
