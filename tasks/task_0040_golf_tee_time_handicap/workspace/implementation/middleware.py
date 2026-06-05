from flask import request
import errors

KNOWN_ROLES = {"ProShop", "Golfer", "Anonymous"}


def get_identity():
    """Returns (role, user_id). Validates header presence and known role.
    Raises ERR_UNAUTHENTICATED when headers missing/invalid."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return role, user_id


def require_auth(allowed_roles):
    """Authenticate, then enforce role membership.

    allowed_roles: set of roles permitted for the operation.
    If 'Anonymous' is in allowed_roles, an unauthenticated caller (missing/invalid
    headers) is still allowed (treated as Anonymous). Otherwise auth is required.
    Returns (role, user_id)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    valid_headers = bool(role) and bool(user_id) and role in KNOWN_ROLES

    if not valid_headers:
        if "Anonymous" in allowed_roles:
            # public endpoint; missing/invalid headers => anonymous browsing allowed
            return "Anonymous", user_id
        raise errors.unauthenticated()

    # headers valid; enforce role permission
    if role not in allowed_roles:
        raise errors.forbidden()
    return role, user_id
