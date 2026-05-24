"""Auth and RBAC middleware.

Auth headers per PRD §2.1:
  - X-User-ID  (acting principal id)
  - X-User-Role (one of: Applicant, Recommender, AdmissionsOfficer,
                 FinancialAidOfficer, PlatformAdmin)

The validation priority ordering is fixed by PRD §2.6:
  1. ERR_MISSING_AUTH_HEADERS
  2. ERR_UNKNOWN_ROLE
  3. ERR_FORBIDDEN_ROLE
  4. (subsequent priorities are handled inside route bodies)
"""

from functools import wraps

from flask import request

import errors


KNOWN_ROLES = frozenset({
    "Applicant",
    "Recommender",
    "AdmissionsOfficer",
    "FinancialAidOfficer",
    "PlatformAdmin",
})


def get_principal():
    """Return (role, user_id) extracted from headers.

    Returns (None, None) when either header is missing.
    Does NOT raise; raising is the caller's responsibility based on whether the
    endpoint is public or protected.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        return None, None
    return role, user_id


def require_auth(allowed_roles):
    """Decorator factory.

    allowed_roles: iterable of role names permitted to invoke this endpoint.
        If the iterable contains "Anonymous", the endpoint is public — no
        headers are required and no role check is performed; ownership checks
        and body validation still apply downstream.
    """
    allowed = frozenset(allowed_roles)
    is_public = "Anonymous" in allowed

    def deco(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            user_id = request.headers.get("X-User-ID")

            if is_public:
                # Public endpoint: accept any request, including ones with no
                # headers at all. Pass through; the handler doesn't depend on
                # principal identity.
                return func(*args, **kwargs)

            # 1) ERR_MISSING_AUTH_HEADERS (priority 1)
            if not role or not user_id:
                errors.raise_error(
                    errors.ERR_MISSING_AUTH_HEADERS,
                    "Both X-User-Role and X-User-ID headers are required.",
                )

            # 2) ERR_UNKNOWN_ROLE (priority 2)
            if role not in KNOWN_ROLES:
                errors.raise_error(
                    errors.ERR_UNKNOWN_ROLE,
                    f"Unknown role: {role!r}.",
                )

            # 3) ERR_FORBIDDEN_ROLE (priority 3)
            if role not in allowed:
                errors.raise_error(
                    errors.ERR_FORBIDDEN_ROLE,
                    f"Role {role!r} is not permitted to call this endpoint.",
                )

            return func(*args, **kwargs)

        return wrapper

    return deco
