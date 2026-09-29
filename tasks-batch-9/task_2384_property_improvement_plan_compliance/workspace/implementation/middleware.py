"""Authentication / authorisation — rejection band 1 (PRD section 2.1, 2.6)."""

from flask import request

from errors import ApiError

FRANCHISEE_OWNER = "FranchiseeOwner"
BRAND_MANAGER = "BrandManager"
BRAND_INSPECTOR = "BrandInspector"

KNOWN_ROLES = (FRANCHISEE_OWNER, BRAND_MANAGER, BRAND_INSPECTOR)

ANY_ROLE = "__any__"

ROLE_HEADER = "X-User-Role"
USER_ID_HEADER = "X-User-ID"

MAX_USER_ID_LEN = 64


def authenticate(allowed_roles):
    """Returns (user_id, role); raises ApiError for band-1 failures."""
    role = request.headers.get(ROLE_HEADER)
    if role is None:
        raise ApiError("ERR_MISSING_ROLE")
    if role not in KNOWN_ROLES:
        raise ApiError("ERR_INVALID_ROLE")

    user_id = request.headers.get(USER_ID_HEADER)
    if user_id is None or len(user_id) < 1 or len(user_id) > MAX_USER_ID_LEN:
        raise ApiError("ERR_MISSING_USER_ID")

    if allowed_roles != ANY_ROLE and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")

    return user_id, role
