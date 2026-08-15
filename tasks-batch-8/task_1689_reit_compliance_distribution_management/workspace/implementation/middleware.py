"""Auth middleware per PRD §2.1 and scaffold validations priorities 1-2.

Every request must carry X-User-ID and X-User-Role. Role must be one of the
declared set {ComplianceOfficer, TaxDirector, BoardDirector}. Missing headers
or unknown role -> ERR_UNAUTHENTICATED (401). Recognized role not permitted
for the endpoint -> ERR_UNAUTHORIZED (403).
"""

from flask import request

import errors

ROLES = ("ComplianceOfficer", "TaxDirector", "BoardDirector")


def get_auth():
    """Extract and validate the auth headers. Returns (user_id, role).

    Raises ApiError(ERR_UNAUTHENTICATED) when headers are missing or role unknown.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Validate auth headers and that the caller's role is in `allowed`.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED then ERR_UNAUTHORIZED.
    """
    user_id, role = get_auth()
    if role not in allowed:
        raise errors.unauthorized()
    return user_id, role
