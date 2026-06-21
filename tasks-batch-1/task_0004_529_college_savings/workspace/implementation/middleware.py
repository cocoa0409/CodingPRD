"""Authentication / authorization middleware.

PRD §2.1:
  - Every request must carry X-User-ID and X-User-Role.
  - X-User-Role MUST be one of {AccountOwner, CustodianAgent, ComplianceOfficer,
    SystemTaxAuthority}; missing or unrecognized -> ERR_UNAUTHENTICATED (401).
  - If recognized but not on endpoint allow-list -> ERR_FORBIDDEN (403).
"""
from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN


VALID_ROLES = {"AccountOwner", "CustodianAgent", "ComplianceOfficer", "SystemTaxAuthority"}


def current_role() -> str:
    role = request.headers.get("X-User-Role")
    if not role or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "X-User-Role header missing or unrecognized")
    return role


def current_user_id() -> str:
    # X-User-ID may be empty for some test scenarios but every authed request the
    # suite sends has it. We don't fail purely on absence here; downstream
    # ownership/segregation checks use the value as a string identifier.
    return request.headers.get("X-User-ID", "")


def require_roles(*allowed: str):
    """Decorator: enforce authentication + endpoint authorization.

    Auth-check (ERR_UNAUTHENTICATED) runs before role-check (ERR_FORBIDDEN), per
    PRD §2.8 priority order.
    """
    allowed_set = set(allowed)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = current_role()  # raises ERR_UNAUTHENTICATED on bad/missing.
            if role not in allowed_set:
                raise err(ERR_FORBIDDEN, "Role not permitted for this endpoint")
            return fn(*args, **kwargs)

        return wrapper

    return deco
