"""Auth middleware: X-User-ID / X-User-Role validation and RBAC.

Identity kinds (PRD 2.1):
- PayrollAdmin / ComplianceOfficer: opaque user ids, never compared to entity ids.
- HouseholdClient: X-User-ID is the acting HouseholdEmployer.id (entity-backed).
- Worker: X-User-ID is the acting DomesticWorker.id (entity-backed).
"""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, HTTP_STATUS

ROLES = {"PayrollAdmin", "ComplianceOfficer", "HouseholdClient", "Worker"}


def get_auth() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError(
            ERR_UNAUTHENTICATED,
            HTTP_STATUS[ERR_UNAUTHENTICATED],
            "X-User-ID and X-User-Role headers are required",
        )
    if role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            HTTP_STATUS[ERR_UNAUTHENTICATED],
            "X-User-Role is not a recognized role",
        )
    return user_id, role


def forbid(message: str = "Role not permitted for this operation") -> None:
    raise ApiError(ERR_FORBIDDEN, HTTP_STATUS[ERR_FORBIDDEN], message)


def require_roles(*allowed: str):
    """Authenticate, then enforce role membership on the endpoint."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                forbid()
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator


def check_employer_ownership(user_id: str, role: str, employer_id: str) -> None:
    """HouseholdClient may only touch their own employer's subgraph."""
    if role == "HouseholdClient" and user_id != employer_id:
        forbid("HouseholdClient identity does not match the owning employer")


def check_worker_ownership(user_id: str, role: str, worker_id: str) -> None:
    """Worker may only touch their own records."""
    if role == "Worker" and user_id != worker_id:
        forbid("Worker identity does not match the owning worker")
