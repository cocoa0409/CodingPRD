"""Auth header extraction and role checking (PRD §2.1, §2.8).

Headers (PRD §2.1):
  X-User-ID   — acting user id (opaque for manager/runner/operator; the Patron's
                entity id when role is Patron)
  X-User-Role — one of ConcessionsManager, StockRunner, StandOperator, Patron

Validation ordering (PRD §2.8): auth (missing header) -> ERR_UNAUTHENTICATED,
then role authorization -> ERR_FORBIDDEN_ROLE. These run before existence and
every business check.
"""

import functools

from flask import g, request

import errors

VALID_ROLES = {"ConcessionsManager", "StockRunner", "StandOperator", "Patron"}


def require_auth(allowed_roles):
    """Decorator enforcing §2.1 auth then RBAC for `allowed_roles`.

    Runs FIRST in the validation chain so ERR_UNAUTHENTICATED / ERR_FORBIDDEN_ROLE
    mask any later existence or business error (PRD §2.8).
    """

    allowed = set(allowed_roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")

            # Priority 1: both headers must be present and non-empty.
            if not user_id or not user_role:
                raise errors.unauthenticated()

            # An unrecognized role cannot be permitted for any endpoint -> 403.
            if user_role not in VALID_ROLES:
                raise errors.forbidden_role()

            # Priority 2: role must be permitted for this endpoint.
            if user_role not in allowed:
                raise errors.forbidden_role()

            g.user_id = user_id
            g.user_role = user_role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
