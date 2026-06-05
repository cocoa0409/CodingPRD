"""Auth header extraction and RBAC enforcement (PRD §2.1, SCAFFOLD §1.4/§1.7).

Auth (priority 1): X-User-ID and X-User-Role must both be present and
X-User-Role must name one of the six known roles, else ERR_UNAUTHENTICATED (401).

Authorization (priority 2): the acting role must be permitted for the endpoint,
else ERR_FORBIDDEN_ROLE (403). X-User-ID is an opaque actor label for all six
roles — never matched against any entity id.
"""
from __future__ import annotations

from functools import wraps
from typing import Optional

from flask import g, request

from errors import APIError, ERR_FORBIDDEN_ROLE, ERR_UNAUTHENTICATED

KNOWN_ROLES = {
    "TerminalAdmin",
    "BerthPlanner",
    "YardPlanner",
    "GateOperator",
    "CustomsOfficer",
    "ReeferTechnician",
}


def require(*allowed_roles):
    """Decorator enforcing auth-then-authorization for an endpoint."""
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            user_id = request.headers.get("X-User-ID")
            # priority 1: authentication
            if not user_id or not role or role not in KNOWN_ROLES:
                raise APIError(ERR_UNAUTHENTICATED, 401, "Missing or unknown auth headers")
            g.user_role = role
            g.user_id = user_id
            # priority 2: authorization
            if role not in allowed:
                raise APIError(ERR_FORBIDDEN_ROLE, 403, "Role not permitted for this endpoint")
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)
