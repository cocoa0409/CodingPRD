"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request

from errors import ApiError

ROLES = ["Analyst", "AssetManager", "IC_Member", "IC_Chair", "Admin"]
READ_ROLES = list(ROLES)  # all five roles can read


def auth(allowed=None):
    """Validate X-User-Role and X-User-ID, optionally enforce endpoint role set.

    Returns (user_id, role).
    Priority order per PRD 2.8:
      1. X-User-Role present and valid -> ERR_UNAUTHENTICATED 401
      2. X-User-ID present and non-empty -> ERR_UNAUTHENTICATED 401
      3. Caller role permitted -> ERR_FORBIDDEN 403
    """
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "Missing or invalid X-User-Role header",
        )
    user_id = request.headers.get("X-User-ID")
    if not user_id:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "Missing or empty X-User-ID header",
        )
    if allowed is not None and role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN",
            403,
            "Caller role is not permitted for this endpoint",
        )
    return user_id, role
