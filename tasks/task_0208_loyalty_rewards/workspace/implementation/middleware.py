"""Auth header extraction and RBAC enforcement (PRD §2.1, §3.11, SCAFFOLD §1.7).

Auth headers (PRD §2.1): X-User-ID and X-User-Role.
Roles: ProgramAdmin, Member, PartnerOperator, Anonymous.
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

KNOWN_ROLES = {"ProgramAdmin", "Member", "PartnerOperator", "Anonymous"}


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED when either header is
    missing or the role is not a recognised value."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_roles(*allowed):
    """Authenticate, then enforce that the caller's role is permitted.

    Priority (PRD §3.11): ERR_UNAUTHENTICATED (401) before ERR_FORBIDDEN (403).
    Anonymous holds no business operations, so it is never in `allowed`.
    Returns (user_id, role).
    """
    user_id, role = get_auth()
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "Role '%s' is not permitted for this operation" % role)
    return user_id, role
