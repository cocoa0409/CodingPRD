"""Auth header extraction and role gating (PRD 2.1, validations priority 1-2).

Header check applies to every endpoint except the two system capabilities
(clock set / daily sweep), which require LibraryAdmin in any case.
"""
from flask import request

from errors import (
    ApiError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)
from util import VALID_ROLES, is_str


def require_auth(*allowed_roles):
    """Priority 1 (headers well-formed) then priority 2 (role permitted)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not is_str(uid) or not is_str(role) or role not in VALID_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and well-formed",
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "Role %s is not permitted for this operation" % role,
        )
    return uid, role


def require_system():
    """System endpoints (clock, sweep): exempt from the priority-1 header
    check, but still restricted to LibraryAdmin."""
    role = request.headers.get("X-User-Role")
    if role != "LibraryAdmin":
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "System capability restricted to LibraryAdmin",
        )
