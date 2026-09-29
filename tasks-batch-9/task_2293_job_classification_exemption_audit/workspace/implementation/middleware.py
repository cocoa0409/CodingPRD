"""Auth header extraction, RBAC and request plumbing (PRD 2.1, 2.3, 2.7)."""
from functools import wraps

from flask import g, request

from constants import ROLES
from errors import fail


def _read_user_context():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    # priority 1: both headers present and non-empty
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        fail("ERR_MISSING_USER_CONTEXT")
    return user_id, role


def endpoint(roles):
    """Wrap a view: rank 1 user context, then rank 2 role authorization."""
    allowed = list(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = _read_user_context()
            # priority 2: known role AND authorized for this endpoint
            if role not in ROLES or role not in allowed:
                fail("ERR_ROLE_NOT_PERMITTED")
            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def body():
    """Parsed JSON object body; an absent or non-object body reads as empty."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def pagination():
    """limit defaults to 10 (1..100), offset defaults to 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset
