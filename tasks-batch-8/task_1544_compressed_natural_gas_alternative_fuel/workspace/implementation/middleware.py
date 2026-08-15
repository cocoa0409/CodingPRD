"""Auth header extraction and role checking (validation stages 1, 2, 5)."""
from __future__ import annotations

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
    ERR_ACCOUNT_OWNERSHIP_MISMATCH,
    ERR_CARD_OWNERSHIP_MISMATCH,
)

ROLES = {
    "NetworkOperator",
    "StationManager",
    "ComplianceOfficer",
    "FleetAccountManager",
    "FleetDriver",
    "Anonymous",
}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role

    def __repr__(self) -> str:  # pragma: no cover
        return f"Caller({self.role}:{self.user_id})"


def get_caller() -> Caller:
    """Stage 1: header presence + role validity."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "" or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and X-User-Role must name a declared role",
        )
    return Caller(user_id=user_id, role=role)


def require_role(caller: Caller, allowed: list[str]) -> None:
    """Stage 2: endpoint role permission."""
    if caller.role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            403,
            f"Role {caller.role} is not permitted for this endpoint",
        )


def check_card_ownership(caller: Caller, fleet_card_id: str) -> None:
    """Stage 5: FleetDriver X-User-ID must equal the referenced fleet_card_id."""
    if caller.role == "FleetDriver" and caller.user_id != fleet_card_id:
        raise ApiError(
            ERR_CARD_OWNERSHIP_MISMATCH,
            403,
            "FleetDriver X-User-ID does not match the referenced fleet_card_id",
        )


def check_account_ownership(caller: Caller, fleet_account_id: str) -> None:
    """Stage 5: FleetAccountManager X-User-ID must equal the referenced fleet_account_id."""
    if caller.role == "FleetAccountManager" and caller.user_id != fleet_account_id:
        raise ApiError(
            ERR_ACCOUNT_OWNERSHIP_MISMATCH,
            403,
            "FleetAccountManager X-User-ID does not match the referenced fleet_account_id",
        )
