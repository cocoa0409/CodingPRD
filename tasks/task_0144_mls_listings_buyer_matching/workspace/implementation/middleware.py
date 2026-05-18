"""Request-scoped auth + RBAC enforcement (scaffold §1.4, PRD §2.1)."""
from __future__ import annotations

from functools import wraps

from flask import g, request

from config import (
    AGENT_ROLE_BUYER,
    AGENT_ROLE_DUAL,
    AGENT_ROLE_LISTING,
    HEADER_USER_ID,
    HEADER_USER_ROLE,
    ROLES,
)
from db import store
from errors import err_auth_invalid, err_auth_missing, err_forbidden


def _read_headers() -> tuple[str, str]:
    role = (request.headers.get(HEADER_USER_ROLE) or "").strip()
    user_id = (request.headers.get(HEADER_USER_ID) or "").strip()
    return role, user_id


def require_auth(allowed_roles):
    """Decorator: enforce auth-header presence + role permission.

    Validation order matches PRD §2.1:
      1. X-User-Role missing/unrecognised header        → ERR_AUTH_MISSING (401)
      2. X-User-ID missing                              → ERR_AUTH_MISSING (401)
      3. X-User-ID doesn't resolve to a valid principal → ERR_AUTH_INVALID (401)
      4. role lacks permission per RBAC                 → ERR_FORBIDDEN    (403)
    """
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    allowed_set = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, user_id = _read_headers()

            # Step 1: role header present and recognised (priority 1 auth check).
            if not role:
                raise err_auth_missing("X-User-Role header missing.")
            if role not in ROLES:
                # Unrecognised role spelling is treated as ERR_AUTH_INVALID
                # per PRD §2.1 ("the role spelling itself is not one of the
                # recognized values").
                raise err_auth_invalid("X-User-Role header value is not recognised.")

            # Step 2: user-id header presence.
            if not user_id:
                raise err_auth_missing("X-User-ID header missing.")

            # Step 3: user-id resolves to a valid principal.
            if role == "MlsAdmin":
                # Opaque operator identity (PRD §2.1).
                pass
            else:
                # Entity-backed: agent must exist and its agent_role must be
                # consistent with X-User-Role.
                agent = store.agents.get(user_id)
                if agent is None:
                    raise err_auth_invalid("X-User-ID does not resolve to an Agent.")
                role_ok = False
                if role == "ListingAgent":
                    role_ok = agent["agent_role"] in (AGENT_ROLE_LISTING, AGENT_ROLE_DUAL)
                elif role == "BuyerAgent":
                    role_ok = agent["agent_role"] in (AGENT_ROLE_BUYER, AGENT_ROLE_DUAL)
                if not role_ok:
                    raise err_auth_invalid(
                        "X-User-Role does not match the resolved Agent's agent_role."
                    )

            # Step 4: RBAC — role permitted on this endpoint.
            if role not in allowed_set:
                raise err_forbidden(
                    f"Role {role} is not permitted for this endpoint."
                )

            g.role = role
            g.user_id = user_id
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_role() -> str:
    return getattr(g, "role", "")


def current_user_id() -> str:
    return getattr(g, "user_id", "")
