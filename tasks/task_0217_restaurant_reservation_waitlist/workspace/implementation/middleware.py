"""Auth header extraction and RBAC (PRD §2.1, §2.10, §1.7).

Auth headers: X-User-ID and X-User-Role. Role is exactly one of
Customer, Host, Manager. Two endpoints skip authentication entirely:
customer self-registration (POST /customers) and the test clock
(POST /_clock/set_current_utc).
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {"Customer", "Host", "Manager"}


def get_auth():
    """Validate and return (user_id, role). Raises ERR_UNAUTHENTICATED if the
    headers are missing or malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "missing or malformed auth headers")
    return user_id, role


def require_roles(allowed):
    """Authenticate, then enforce that the caller's role is in `allowed`.

    Returns (user_id, role). Auth (401) is checked before role (403), per the
    validation ordering of PRD §2.10.
    """
    user_id, role = get_auth()
    if role not in allowed:
        raise err(ERR_FORBIDDEN, f"role {role} is not permitted for this operation")
    return user_id, role
