"""Auth header extraction and RBAC. Header names and role values come verbatim
from PRD §2.1."""
from flask import request

import errors

KNOWN_ROLES = {"Customer", "StoreAssociate", "ComplianceOfficer", "Admin", "Anonymous"}


def get_principal(allow_anonymous=False):
    """PRD §2.1: X-User-Role + X-User-ID. Missing/unknown role -> 401.
    The Anonymous role needs no X-User-ID. Every other role requires X-User-ID."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    user_id = request.headers.get("X-User-ID")
    if role == "Anonymous":
        return role, user_id
    # All non-Anonymous roles must carry an X-User-ID.
    if user_id is None:
        raise errors.unauthenticated()
    return role, user_id


def require_roles(allowed_roles):
    """Authenticate (401) then authorize role (403) in PRD §2.10 precedence order.
    Returns (role, user_id)."""
    role, user_id = get_principal()
    if role not in allowed_roles:
        raise errors.forbidden()
    return role, user_id
