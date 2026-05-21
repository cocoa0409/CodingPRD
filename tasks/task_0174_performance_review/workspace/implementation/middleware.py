"""Auth header validation and request-scoped identity bootstrap.

Auth contract (SCAFFOLD validations 10/20/30 and PRD §2.1):
- Every request must carry X-User-ID and X-User-Role; otherwise ERR_AUTH_REQUIRED.
- X-User-Role must be one of {Admin, HRBP, Manager, Reviewer, Approver};
  otherwise ERR_INVALID_ROLE.
- Endpoint-level RBAC (priority 30) is enforced per-route via require_role().
"""

from functools import wraps
from typing import Iterable

from flask import g, request

from config import VALID_ROLES
from db import new_request_id
from errors import raise_err

# Open paths: nothing in this API is unauthenticated, but we still need
# auth to run after request-id minting.
EXEMPT_PATHS: set = set()


def before_request_hook() -> None:
    """Mint a request id and validate auth headers."""
    g.api_request_id = new_request_id()

    # Allow flask error responses to flow through; only check on dispatched routes.
    if request.path in EXEMPT_PATHS:
        return

    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")

    if not user_id or not user_role:
        raise_err(
            "ERR_AUTH_REQUIRED",
            "X-User-ID and X-User-Role headers are required.",
        )

    if user_role not in VALID_ROLES:
        raise_err(
            "ERR_INVALID_ROLE",
            f"X-User-Role '{user_role}' is not one of {sorted(VALID_ROLES)}.",
        )

    g.user_id = user_id
    g.user_role = user_role


def require_role(*allowed_roles: str):
    """Endpoint-level RBAC enforcement. Use as a decorator."""

    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = getattr(g, "user_role", None)
            if role not in allowed:
                raise_err(
                    "ERR_ROLE_FORBIDDEN",
                    f"Role '{role}' is not permitted for this endpoint.",
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def role_in(*roles: str) -> bool:
    return getattr(g, "user_role", None) in set(roles)


def current_actor():
    """Return (user_id, role) for the current request, used by the audit log."""
    return getattr(g, "user_id", None), getattr(g, "user_role", None)
