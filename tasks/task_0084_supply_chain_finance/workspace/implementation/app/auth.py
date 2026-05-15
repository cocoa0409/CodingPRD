"""Authentication and RBAC (PRD §2.1).

Every request must carry X-User-ID and X-User-Role headers.
Recognised roles: CoreEnterpriseUser, SupplierUser, CreditOfficer,
ComplianceOfficer, RiskReviewer, CreditApprover, Funder,
CollectionManager, PlatformAdmin.
"""
from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import g, request

from .constants import VALID_ROLES
from .errors import api_error


def parse_auth():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise api_error("ERR_AUTH_HEADER_MISSING", "X-User-ID or X-User-Role header missing")
    if user_role not in VALID_ROLES:
        raise api_error("ERR_AUTH_ROLE_UNKNOWN", f"Unrecognised role: {user_role}")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_auth(roles: Iterable[str]):
    """Decorator: ensure auth headers are present and role is permitted."""
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = parse_auth()
            if role not in allowed:
                raise api_error("ERR_FORBIDDEN", f"Role {role} not permitted")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
