"""Request user-context extraction and RBAC (PRD §2.1, §2.9, §4).

Every request must carry X-User-ID and X-User-Role. If either is missing, or
X-User-Role is not one of the declared roles, reject with
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400). When headers are well-formed
but the role/identity is not permitted, reject with ERR_UNAUTHORIZED (403).
"""
from flask import request

import errors

ROLES = ("Anonymous", "Member", "PlatformOps", "PlatformAdmin")


class Ctx(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_context():
    """Validate the user-context headers; return a Ctx or raise ApiError(400)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    return Ctx(user_id, role)


def require_role(ctx, *allowed):
    """Reject with ERR_UNAUTHORIZED (403) unless the acting role is allowed."""
    if ctx.role not in allowed:
        raise errors.err(errors.ERR_UNAUTHORIZED)
