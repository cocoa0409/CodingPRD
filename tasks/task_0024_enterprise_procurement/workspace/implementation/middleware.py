"""Auth header parsing and RBAC helpers (PRD §2.1 / §2.8 priorities 1-4)."""

from __future__ import annotations

from functools import wraps

from flask import g, request

from db import db
from errors import err

VALID_ROLES = {
    "Requester",
    "Buyer",
    "DepartmentHead",
    "FinanceApprover",
    "LegalApprover",
    "GeneralManager",
    "Inspector",
    "Supplier",
    "PlatformAdmin",
}

# Roles whose X-User-ID maps to a stored entity (PRD §2.1 last paragraph).
ENTITY_BACKED_ROLES = {"Supplier"}


def _extract_user_context():
    """Priority 1: auth headers present and non-empty.
    Priority 2: role recognized; entity-backed roles must resolve to a stored entity.
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if user_id is None or user_role is None or user_id == "" or user_role == "":
        raise err(
            "ERR_AUTH_REQUIRED",
            "X-User-ID and X-User-Role headers are required.",
        )
    if not isinstance(user_id, str) or not isinstance(user_role, str):
        raise err("ERR_AUTH_REQUIRED")
    if user_role.strip() == "" or user_id.strip() == "":
        raise err("ERR_AUTH_REQUIRED")
    # priority 2 — recognized role
    if user_role not in VALID_ROLES:
        raise err(
            "ERR_FORBIDDEN",
            f"Unknown role '{user_role}'.",
        )
    # priority 2 — entity-backed identity must resolve to a stored entity
    if user_role in ENTITY_BACKED_ROLES:
        if user_role == "Supplier" and user_id not in db.suppliers:
            raise err(
                "ERR_FORBIDDEN",
                "Supplier identity does not resolve to a known supplier.",
            )
    g.user_id = user_id
    g.user_role = user_role


def require_auth():
    """Decorator: validate auth context (priority 1 + 2). Use on any endpoint."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _extract_user_context()
            return fn(*args, **kwargs)

        return wrapper

    return deco


def require_roles(*roles: str):
    """Decorator: enforce that the caller's X-User-Role is in `roles` (priority 4).

    For endpoints that accept path parameters, existence (priority 3) must
    run BEFORE role check (priority 4). This decorator therefore only checks
    auth headers (priority 1+2) and stores the requested role-set on flask.g
    so the handler can run path-param existence first and then call
    enforce_role(). For endpoints WITHOUT path parameters, the decorator
    enforces the role set immediately, which is the same as priority 4
    coming right after priority 1+2.
    """

    role_set = set(roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _extract_user_context()
            # Stash the requested role set so handlers (those with path params)
            # can defer the role check until after existence checks.
            g.allowed_roles = role_set
            # If this endpoint has no URL kwargs, we can do the role check
            # right away — there are no path params to resolve first.
            if not kwargs:
                if g.user_role not in role_set:
                    raise err(
                        "ERR_FORBIDDEN",
                        f"Role '{g.user_role}' is not permitted for this operation.",
                    )
            return fn(*args, **kwargs)

        return wrapper

    return deco


def enforce_role() -> None:
    """Run the deferred role check (priority 4). Call from handlers that took
    path parameters, AFTER all path-existence checks have passed."""
    role_set = getattr(g, "allowed_roles", None)
    if role_set is None:
        return  # nothing requested — nothing to enforce.
    if g.user_role not in role_set:
        raise err(
            "ERR_FORBIDDEN",
            f"Role '{g.user_role}' is not permitted for this operation.",
        )


def current_actor() -> tuple[str, str]:
    return getattr(g, "user_id", "system"), getattr(g, "user_role", "system")
