"""Authentication / RBAC helpers.

PRD §2.1: every request must carry X-User-ID and X-User-Role headers. The
allowed roles are Applicant, Landlord, Inspector, CaseWorker,
PortabilityCoordinator, PHAAdmin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from flask import request

from app.errors import APIError, auth_required, forbidden_role


VALID_ROLES = {
    "Applicant",
    "Landlord",
    "Inspector",
    "CaseWorker",
    "PortabilityCoordinator",
    "PHAAdmin",
}


@dataclass
class Caller:
    user_id: str
    role: str


def authenticate() -> Caller:
    """Validate auth headers in priority order: presence then role string."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise auth_required()
    if role not in VALID_ROLES:
        raise forbidden_role(f"Unknown role '{role}'")
    return Caller(user_id=user_id, role=role)


def require_role(caller: Caller, allowed: Iterable[str]) -> None:
    """Reject the caller unless their role is in `allowed`."""
    allowed = set(allowed)
    if caller.role not in allowed:
        raise forbidden_role(
            f"Role {caller.role} not permitted; allowed roles: {sorted(allowed)}"
        )
