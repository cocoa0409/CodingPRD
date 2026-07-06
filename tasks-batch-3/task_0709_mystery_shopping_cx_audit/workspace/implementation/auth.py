"""Authentication & RBAC (PRD 2.1).

Every request (except public self-registration of a client/shopper) must carry
two headers: X-User-ID and X-User-Role. Missing/malformed -> ERR_UNAUTHENTICATED.
A recognized but unauthorized role -> ERR_FORBIDDEN_ROLE.
"""
from flask import request

from errors import err

ROLES = {"Anonymous", "PlatformAdmin", "ClientManager", "Shopper", "QaValidator", "FinanceOfficer"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate the auth headers. Returns Caller or raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-ID header.")
    if not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-Role header.")
    return Caller(user_id.strip(), role)


def require_roles(caller, allowed):
    """Enforce that caller.role is one of `allowed` (RBAC) -> ERR_FORBIDDEN_ROLE."""
    if caller.role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s may not invoke this operation." % caller.role)
