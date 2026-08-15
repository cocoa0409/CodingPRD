"""Auth context extraction and role gating (PRD sections 2.1, 2.6 tiers 1-2)."""
from flask import request

from errors import err_missing_context, err_forbidden_role

ROLES = {"GardenAdmin", "Coordinator", "Volunteer", "GroupLeader", "FoodSafetyOfficer"}
ALL_ROLES = ["GardenAdmin", "Coordinator", "Volunteer", "GroupLeader", "FoodSafetyOfficer"]
SELF_SERVICE_ROLES = {"Volunteer", "GroupLeader", "FoodSafetyOfficer"}


class Ctx:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def require_auth() -> Ctx:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_missing_context()
    return Ctx(user_id, role)


def require_role(ctx: Ctx, allowed):
    if ctx.role not in allowed:
        raise err_forbidden_role()
