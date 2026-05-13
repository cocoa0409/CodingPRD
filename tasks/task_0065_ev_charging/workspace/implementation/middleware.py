"""Authentication and authorization helpers."""

from functools import wraps
from typing import Iterable

from flask import g, request

import db
from errors import raise_error


VALID_ROLES = {
    "PlatformOperator",
    "StationOwner",
    "EVDriver",
    "FieldTechnician",
    "CustomerService",
}

OPAQUE_ROLES = {"PlatformOperator", "FieldTechnician", "CustomerService"}


def _extract_headers():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    return role, user_id


def authenticate():
    """Validate auth headers per the priority-1/2/3 rules.

    Returns (role, user_id) tuple. Raises APIError otherwise.
    """
    role, user_id = _extract_headers()
    # Priority 1: missing headers
    if not role or not user_id:
        raise_error("ERR_AUTH_MISSING", "X-User-Role and X-User-ID are required")
    # Priority 2: invalid role value
    if role not in VALID_ROLES:
        raise_error("ERR_AUTH_INVALID", "X-User-Role not recognized")
    # Entity-backed roles (StationOwner, EVDriver) do NOT verify X-User-ID
    # against the Operator/Member table at auth time. PRD §2.1 describes
    # X-User-ID for these roles as the value used in *ownership* checks
    # against the resource's foreign-key field; PRD §2.5 places resource
    # existence checks AFTER authentication. So a request with a non-matching
    # X-User-ID is rejected at the resource layer (ERR_NOT_FOUND when the
    # path resource is missing, ERR_FORBIDDEN when ownership compare fails).
    g.role = role
    g.user_id = user_id
    return role, user_id


def require_roles(allowed: Iterable[str]):
    """Decorator that authenticates and enforces RBAC.

    Test harness endpoints (`/_clock/advance`, `/_sweep/run`, `/_events/emit`)
    are exempt from the priority-1 missing-header check per §2.1 of the PRD.
    """
    allowed = set(allowed)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, user_id = _extract_headers()
            path = request.path
            test_harness = path.startswith("/_clock/") or path.startswith(
                "/_sweep/"
            ) or path.startswith("/_events/")

            if test_harness:
                # Bypass priority-1 missing-header check; require role only if
                # present and reject invalid roles. Default to PlatformOperator
                # when both headers are absent so that automation can call.
                if role is None and user_id is None:
                    role = "PlatformOperator"
                    user_id = "test-harness"
                else:
                    if not role:
                        raise_error("ERR_AUTH_MISSING", "X-User-Role required")
                    if role not in VALID_ROLES:
                        raise_error("ERR_AUTH_INVALID", "X-User-Role not recognized")
                g.role = role
                g.user_id = user_id
            else:
                authenticate()
                role = g.role
                user_id = g.user_id

            if role not in allowed:
                raise_error("ERR_FORBIDDEN", f"role {role} not authorized")

            return fn(*args, **kwargs)

        return wrapper

    return decorator
