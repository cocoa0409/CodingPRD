"""Auth middleware: X-User-ID / X-User-Role headers and RBAC (PRD §2.1,
validation cascade priorities 1-2 and 4).

Eleven declared roles. Ten are opaque; PracticeGroupRep is entity-backed:
its X-User-ID must equal the id of the PracticeGroup owning the targeted
settlement/dispute's contract.
"""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import (
    ApiError,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_FORBIDDEN_GROUP_SCOPE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    HTTP_STATUS,
)

ROLES = {
    "PayerAdmin",
    "ContractManager",
    "AttributionAnalyst",
    "ActuaryAnalyst",
    "QualityAnalyst",
    "ClaimsProcessor",
    "SettlementOfficer",
    "DisputeAdjudicator",
    "PaymentOps",
    "Auditor",
    "PracticeGroupRep",
}

ALL_ROLES = tuple(sorted(ROLES))


def get_auth() -> tuple[str, str]:
    """Cascade priority 1: headers present and role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or user_id.strip() == ""
        or role is None
        or role.strip() == ""
        or role not in ROLES
    ):
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            HTTP_STATUS[ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER],
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate (priority 1), then enforce role membership
    (priority 2)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                raise ApiError(
                    ERR_FORBIDDEN_FOR_ROLE,
                    HTTP_STATUS[ERR_FORBIDDEN_FOR_ROLE],
                    "Role not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator


def check_group_scope(user_id: str, role: str, practice_group_id: str) -> None:
    """Cascade priority 4: a PracticeGroupRep caller's X-User-ID must equal the
    id of the PracticeGroup owning the targeted resource's contract."""
    if role != "PracticeGroupRep":
        return
    if user_id != practice_group_id:
        raise ApiError(
            ERR_FORBIDDEN_GROUP_SCOPE,
            HTTP_STATUS[ERR_FORBIDDEN_GROUP_SCOPE],
            "PracticeGroupRep may only access resources of their own group",
        )
