"""Auth header extraction and role checks (PRD §2.1; validation priorities 1-2)."""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ALL_ROLES = {"PlatformAdmin", "AssetManager", "Broker", "LandlordCounsel"}
READ_ROLES = ["PlatformAdmin", "AssetManager", "Broker", "LandlordCounsel"]


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-ID present; X-User-Role present and a declared role."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-ID and a recognized X-User-Role header are required")
    return Caller(user_id, role)


def authorized(allowed_roles) -> Caller:
    """Priorities 1-2: header presence/validity, then role permission."""
    caller = get_caller()
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN,
                    f"role {caller.role} is not permitted for this endpoint")
    return caller
