"""Auth header extraction + role checks per PRD §2.1."""
from flask import request

import errors

ROLES = {
    "SystemAdmin",
    "CityClerk",
    "CityEngineer",
    "FinanceOfficer",
    "CouncilPresident",
    "PropertyOwner",
}

ALL_ROLES = [
    "SystemAdmin", "CityClerk", "CityEngineer",
    "FinanceOfficer", "CouncilPresident", "PropertyOwner",
]
# Roles allowed on staff-only read endpoints (no PropertyOwner).
STAFF_ROLES = [
    "SystemAdmin", "CityClerk", "CityEngineer", "FinanceOfficer", "CouncilPresident",
]
# Roles allowed on owner-flavored read endpoints (no CityEngineer).
OWNER_READ_ROLES = [
    "SystemAdmin", "CityClerk", "FinanceOfficer", "CouncilPresident", "PropertyOwner",
]


class Ctx:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        errors.raise_err(
            errors.MISSING_CTX,
            "X-User-ID and X-User-Role headers are required and the role must be a declared role",
        )
    return Ctx(user_id, role)


def require_role(ctx, allowed):
    if ctx.role not in allowed:
        errors.raise_err(
            errors.UNAUTHORIZED_ROLE,
            f"Role {ctx.role} is not authorized for this endpoint",
        )
