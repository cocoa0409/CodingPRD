"""Auth header extraction and RBAC checks per PRD §2.1 / SCAFFOLD §1.4."""
from __future__ import annotations

from functools import wraps
from typing import Iterable, Optional

from flask import g, request

from errors import (
    APIError,
    ERR_FORBIDDEN_ROLE,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)

# Recognized roles per scaffold/PRD §2.1
RECOGNIZED_ROLES = {"Borrower", "LoanServicer", "PSLFAdjudicator", "VADischargeOfficer"}

# Endpoints that do not require authentication. Only POST /v1/borrowers per SCAFFOLD §1.4 priority 1.
PUBLIC_ENDPOINTS = {("POST", "/v1/borrowers")}


def _is_public(method: str, path: str) -> bool:
    return (method, path) in PUBLIC_ENDPOINTS


def extract_auth() -> None:
    """Populate flask.g with user_id and role; raise APIError on auth failures."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    g.user_id = user_id
    g.user_role = role

    if _is_public(request.method, request.path):
        # Public endpoint: skip both auth checks entirely.
        # If headers happen to be provided, we still accept (no harm).
        return

    # Priority 1: Authentication
    if not user_id or not role:
        raise APIError(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")

    # Priority 2: Role must be recognized
    if role not in RECOGNIZED_ROLES:
        raise APIError(ERR_UNAUTHORIZED, f"Unknown role: {role}")


def require_roles(allowed: Iterable[str]):
    """Decorator: priority 10 check — role permitted to invoke this endpoint."""
    allowed_set = set(allowed)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = getattr(g, "user_role", None)
            # Public endpoint short-circuit: extract_auth may not have set role.
            # require_roles is only attached to non-public endpoints, so role must be set.
            if role not in allowed_set:
                raise APIError(ERR_FORBIDDEN_ROLE, f"Role {role} not permitted for this endpoint")
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)
