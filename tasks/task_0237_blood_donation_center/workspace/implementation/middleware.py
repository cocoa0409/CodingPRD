"""Auth header extraction and RBAC enforcement.

Per PRD §2.1: every request must carry X-User-ID and X-User-Role. The five
recognized roles are spelled exactly: CenterAdmin, IntakeNurse, LabTechnician,
InventoryManager, Donor. Missing header or unknown role ->
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400). Well-formed but not permitted
-> ERR_INSUFFICIENT_PERMISSIONS (403).
"""
from functools import wraps

from flask import g, request

import errors
from errors import ApiError

KNOWN_ROLES = {"CenterAdmin", "IntakeNurse", "LabTechnician", "InventoryManager", "Donor"}


def _extract_context():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in KNOWN_ROLES:
        raise ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "Missing or invalid X-User-ID / X-User-Role header.",
        )
    g.user_id = user_id
    g.user_role = user_role


def require_roles(*allowed):
    """Decorator: validate auth context (priority 1) then role (priority 2)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _extract_context()
            if g.user_role not in allowed:
                raise ApiError(
                    errors.ERR_INSUFFICIENT_PERMISSIONS,
                    403,
                    "Role '%s' is not permitted for this operation." % g.user_role,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
