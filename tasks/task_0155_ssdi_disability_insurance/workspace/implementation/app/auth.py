"""Authentication / RBAC helpers (PRD §2.1).

Every request must carry X-User-ID and X-User-Role headers. The allowed
roles are Claimant, DDS_Examiner, ALJ, AppealsCouncil, CDR_Reviewer,
PlatformAdmin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from flask import request

from app.errors import APIError, auth_required, forbidden, invalid_role


VALID_ROLES = {
    "Claimant",
    "DDS_Examiner",
    "ALJ",
    "AppealsCouncil",
    "CDR_Reviewer",
    "PlatformAdmin",
}


@dataclass
class Caller:
    user_id: str
    role: str


def authenticate() -> Caller:
    """Validate auth headers — presence first (ERR_AUTH_REQUIRED),
    then role membership (ERR_INVALID_ROLE)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise auth_required()
    if role not in VALID_ROLES:
        raise invalid_role(f"Unknown role '{role}'")
    return Caller(user_id=user_id, role=role)


def require_role(caller: Caller, allowed: Iterable[str]) -> None:
    allowed_set = set(allowed)
    if caller.role not in allowed_set:
        raise forbidden(
            f"Role {caller.role} not permitted; allowed roles: {sorted(allowed_set)}"
        )
