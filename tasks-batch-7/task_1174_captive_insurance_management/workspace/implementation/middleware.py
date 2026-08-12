"""Auth context extraction and role checks (PRD 2.1)."""
from __future__ import annotations

from flask import request

from errors import ApiError

ROLES = [
    "CaptiveManager",
    "DomicileRegulator",
    "Underwriter",
    "Actuary",
    "ClaimsAdjuster",
    "BoardDirector",
    "TaxAdvisor",
]

_ROLE_SET = set(ROLES)


def current_actor() -> tuple[str, str]:
    """Return (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and valid",
        )
    if not role or role not in _ROLE_SET:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and valid",
        )
    return user_id, role


def require_roles(*roles: str) -> tuple[str, str]:
    """Auth priority 1 then 2: validate context headers, then role permission."""
    user_id, role = current_actor()
    if role not in roles:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "Current role does not have permission for this operation",
        )
    return user_id, role
