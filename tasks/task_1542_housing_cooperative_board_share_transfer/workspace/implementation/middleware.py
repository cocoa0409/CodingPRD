"""Auth context extraction and role authorization per PRD §2.1 / §2.9."""
from flask import request

from errors import ApiError, ERR_MISSING_CONTEXT_HEADER, ERR_UNAUTHORIZED_ROLE

ALL_ROLES = ("PlatformAdmin", "BoardOfficer", "BoardMember", "ManagingAgent", "Shareholder")


def ctx():
    """Extract and validate X-User-ID / X-User-Role. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip() or role is None or not str(role).strip():
        raise ApiError(
            ERR_MISSING_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and well-formed",
            400,
        )
    return uid.strip(), role.strip()


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED_ROLE,
            "Role %s is not permitted for this endpoint" % role,
            403,
        )
