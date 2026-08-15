"""Auth middleware: X-User-ID / X-User-Role header extraction and role checks."""

from flask import request

from errors import err_unauthenticated, err_forbidden

VALID_ROLES = {
    "PayrollAdmin",
    "ProductionAccountant",
    "PayrollClerk",
    "PayrollSupervisor",
    "UnionAuditor",
}

ALL_ROLES = VALID_ROLES  # read surface is shared across every role


def current_user():
    """Extract and validate the auth headers. Returns (user_id, role)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in VALID_ROLES:
        raise err_unauthenticated()
    if user_id is None or user_id.strip() == "":
        raise err_unauthenticated()
    return user_id, role


def require_roles(allowed_roles):
    """Validate auth headers then enforce the endpoint's role gate.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED (401) first, then
    ERR_FORBIDDEN (403) — the scaffold's validation priority order.
    """
    user_id, role = current_user()
    if role not in allowed_roles:
        raise err_forbidden()
    return user_id, role
