"""Auth header extraction and role checking (PRD §2.1, scaffold validations 1-2)."""
from flask import request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)

ROLES = [
    "TerminalManager",
    "PoolAdministrator",
    "YardPlanner",
    "RailCoordinator",
    "GateSupervisor",
    "GateClerk",
    "MaintenancePlanner",
    "BillingClerk",
]

ALL_ROLES = list(ROLES)


def auth(allowed=None):
    """Validate X-User-ID / X-User-Role; optionally enforce an endpoint role set.

    Returns (user_id, role). Authentication (401) precedes authorization (403).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "Missing or malformed X-User-Role / X-User-ID headers",
        )
    if allowed is not None and role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED, 403, "Role is not authorized for this endpoint"
        )
    return user_id, role
