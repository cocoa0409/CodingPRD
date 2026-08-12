"""Auth middleware per PRD §2.1.

Every request carries X-User-ID and X-User-Role. Role must be one of the five
declared roles; otherwise ERR_UNAUTHENTICATED (401). Endpoint-level role
permission is checked separately and yields ERR_UNAUTHORIZED (403).
"""

from flask import request

import errors

ROLES = {"Customer", "CustomerService", "OperationsManager", "RoutePlanner", "Driver"}


class AuthContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def is_customer(self):
        return self.role == "Customer"

    def is_ops_manager(self):
        return self.role == "OperationsManager"


def get_auth():
    """Validate auth headers. Raises APIError on failure. Returns AuthContext."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.unauthenticated()
    if role not in ROLES:
        raise errors.unauthenticated()
    return AuthContext(user_id, role)


def require_roles(*allowed):
    """Check role is in allowed set. OperationsManager hierarchical override is
    applied: if CustomerService or RoutePlanner is allowed, OperationsManager is
    implicitly allowed (PRD §2.1: 'an OperationsManager may perform every
    operation available to CustomerService and RoutePlanner').
    """
    auth = get_auth()
    effective = set(allowed)
    if "CustomerService" in effective or "RoutePlanner" in effective:
        effective.add("OperationsManager")
    if auth.role not in effective:
        raise errors.unauthorized()
    return auth
