"""Auth header extraction and role checking (PRD §2.1, validations §1.4)."""
from flask import request

from errors import ApiError

VALID_ROLES = {"Agent", "CastingDirector", "Talent"}


def get_identity():
    """Return (user_id, role) after validating presence and well-formedness.

    Auth headers: X-User-ID and X-User-Role. A missing header, an empty value,
    or a role outside the recognized set fails with ERR_UNAUTHENTICATED (401),
    which is priority 1 (checked before everything else).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: ERR_FORBIDDEN_ROLE (403) when the role is not permitted."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE")
