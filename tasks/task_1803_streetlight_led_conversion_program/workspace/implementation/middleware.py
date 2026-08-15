"""Auth (PRD 2.1) and validation-pipeline stages 1/3, plus the store lock."""
import functools

from flask import request

from db import store
from errors import raise_error

ROLES = {
    "ProgramManager",
    "FieldSupervisor",
    "QaInspector",
    "BillingAnalyst",
    "ComplianceOfficer",
    "CitizenReporter",
    "Auditor",
}

ALL_ROLES = sorted(ROLES)


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Stage 1: X-User-ID and X-User-Role present; role declared."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ROLES:
        raise_error(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and X-User-Role must be a declared role",
        )
    return Caller(user_id, role)


def require_roles(caller: Caller, allowed):
    """Stage 3: role permitted on this endpoint."""
    if caller.role not in allowed:
        raise_error("ERR_FORBIDDEN", f"role {caller.role} is not permitted on this endpoint")


def locked(fn):
    """Serialize requests against the in-memory store (atomic multi-step ops)."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with store.lock:
            return fn(*args, **kwargs)

    return wrapper
