"""Auth header extraction and role checking (PRD §2.1).

Headers: X-User-ID and X-User-Role. Roles: Commuter, ParkingAdmin,
EnforcementOfficer, AppealsOfficer.
"""
from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
)

ROLES = ("Commuter", "ParkingAdmin", "EnforcementOfficer", "AppealsOfficer")
ALL_ROLES = list(ROLES)


class CallerContext:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role

    @property
    def is_commuter(self) -> bool:
        return self.role == "Commuter"


def get_caller() -> CallerContext:
    """Priority 1: headers present and role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            401,
            "X-User-ID and X-User-Role headers are required and role must be one of: "
            + ", ".join(ROLES),
        )
    return CallerContext(user_id=user_id, role=role)


def require_roles(caller: CallerContext, allowed: list[str]):
    """Priority 2: role in endpoint's authorized list."""
    if caller.role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            403,
            f"Role {caller.role} is not authorized for this endpoint",
        )


def require_ownership(caller: CallerContext, patron_id: str):
    """Priority 3: a Commuter's X-User-ID must equal the target's patron_id.

    Non-Commuter roles (e.g. ParkingAdmin) are not subject to this check.
    """
    if caller.is_commuter and caller.user_id != patron_id:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            403,
            "Commuter may only act on resources owned by their patron_id",
        )
