"""Auth header extraction and role checking per PRD §2.1."""

from flask import request

import errors

ROLES = {
    "IntakeCoordinator",
    "VisionSpecialist",
    "FundingCoordinator",
    "PayerAdjudicator",
    "BillingSpecialist",
    "RepairTechnician",
    "ClinicAdmin",
}

ALL_ROLES = sorted(ROLES)


class Actor:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_actor() -> Actor:
    """Priority 1: headers present and role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return Actor(user_id=user_id, role=role)


def require_roles(allowed):
    """Priority 2: acting role listed for the endpoint."""
    actor = get_actor()
    if actor.role not in allowed:
        raise errors.forbidden_role()
    return actor
