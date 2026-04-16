from flask import request
from errors import raise_error, ERR_AUTH_REQUIRED, ERR_FORBIDDEN

VALID_ROLES = {"ShelterManager", "CaseWorker", "Veterinarian"}


def get_auth():
    """Extract and validate auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if not user_id or not role:
        raise_error(ERR_AUTH_REQUIRED, "Missing X-User-ID or X-User-Role header")

    if role not in VALID_ROLES:
        raise_error(ERR_AUTH_REQUIRED, "Invalid role")

    return user_id, role


def require_roles(*allowed_roles):
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise_error(ERR_FORBIDDEN, "Insufficient role for this operation")
    return user_id, role


def parse_pagination():
    """Extract limit/offset; raise ERR_INVALID_REQUEST on invalid values."""
    from errors import ERR_INVALID_REQUEST
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = 20
    offset = 0

    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")

    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be non-negative")

    return limit, offset
