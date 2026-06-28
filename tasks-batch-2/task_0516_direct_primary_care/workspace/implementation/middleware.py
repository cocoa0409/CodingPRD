"""Auth header extraction and role checking (PRD §2.1, §3.14)."""
from flask import request

import errors

KNOWN_ROLES = {"PlatformAdmin", "Provider", "Member", "Employer", "Anonymous"}
ENTITY_BACKED = {"Provider", "Member", "Employer"}


class Caller(object):
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id


def authenticate():
    """Validate X-User-ID and X-User-Role headers.

    Returns a Caller. Raises ERR_UNAUTHENTICATED when either header is missing
    or X-User-Role is not a recognized role.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise errors.unauthenticated("Missing X-User-ID or X-User-Role header.")
    if role not in KNOWN_ROLES:
        raise errors.unauthenticated("Unknown X-User-Role: %s" % role)
    return Caller(role, user_id)


def require_roles(caller, allowed_roles):
    """Raise ERR_FORBIDDEN when the caller's role is not in allowed_roles."""
    if caller.role not in allowed_roles:
        raise errors.forbidden(
            "Role %s is not permitted to perform this operation." % caller.role
        )
