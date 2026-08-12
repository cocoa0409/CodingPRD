"""Auth header extraction and role checks per PRD section 2.1.

Every request must carry X-User-ID and X-User-Role. Missing headers,
undeclared roles, and Anonymous are unauthenticated (401). A role not
listed for an endpoint, or an entity-backed identity mismatch, is 403.
"""

from flask import request

from errors import ERR_FORBIDDEN, ERR_UNAUTHENTICATED, raise_err

DECLARED_ROLES = {
    "ProgramAdmin",
    "HiringManager",
    "SupplierCoordinator",
    "FinanceAnalyst",
    "Worker",
}

ALL_READ = (
    "ProgramAdmin",
    "HiringManager",
    "SupplierCoordinator",
    "FinanceAnalyst",
    "Worker",
)
NO_WORKER_READ = ("ProgramAdmin", "HiringManager", "SupplierCoordinator", "FinanceAnalyst")


def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in DECLARED_ROLES:
        raise_err(
            ERR_UNAUTHENTICATED,
            "Missing or invalid X-User-ID / X-User-Role headers.",
        )
    return uid, role


def require_roles(*roles):
    uid, role = require_auth()
    if role not in roles:
        raise_err(ERR_FORBIDDEN, f"Role {role} is not permitted on this endpoint.")
    return uid, role
