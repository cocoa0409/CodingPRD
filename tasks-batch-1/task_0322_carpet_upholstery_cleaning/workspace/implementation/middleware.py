"""Auth header extraction and RBAC (PRD §2.1, §2.6 precedence; scaffold §1.7).

Headers (verbatim from PRD §2.1):
  X-User-ID    — acting principal id
  X-User-Role  — operational capacity; one of exactly:
                 Customer, Dispatcher, ServiceManager, Billing
"""
from __future__ import annotations

from typing import Iterable, Optional

from flask import g, request

from errors import (
    APIError,
    ERR_FORBIDDEN_ROLE,
    ERR_MISSING_AUTH,
)

# The system recognizes exactly four roles, spelled precisely (PRD §2.1).
KNOWN_ROLES = {"Customer", "Dispatcher", "ServiceManager", "Billing"}


def authenticate() -> None:
    """Validate presence + recognition of the auth headers (priority 1).

    Both X-User-ID and X-User-Role must be present, and X-User-Role must name a
    recognized role; otherwise ERR_MISSING_AUTH (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise APIError(ERR_MISSING_AUTH, 401, "Missing or invalid authentication headers")
    g.user_id = user_id
    g.user_role = role


def authorize(allowed_roles: Iterable[str]) -> None:
    """RBAC check (priority 2). Caller's role must be in the allowed set,
    otherwise ERR_FORBIDDEN_ROLE (403).

    Note: ServiceManager is a superset operator. Wherever ServiceManager is an
    authorized role for an operation it is listed explicitly in allowed_roles
    per the PRD endpoint table, so no implicit widening is needed here.
    """
    if g.user_role not in set(allowed_roles):
        raise APIError(ERR_FORBIDDEN_ROLE, 403, "Role not permitted for this operation")


def require(allowed_roles: Iterable[str]) -> None:
    """Convenience: run auth (priority 1) then RBAC (priority 2) in order."""
    authenticate()
    authorize(allowed_roles)


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)


def is_customer() -> bool:
    return current_role() == "Customer"
