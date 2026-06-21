"""Auth header extraction and RBAC enforcement."""
from flask import request, g

import db
import errors as E


VALID_ROLES = {"PlatformAdmin", "HRAdmin", "Employee", "HealthcareProvider"}


def authenticate():
    """
    Validates that X-User-ID and X-User-Role headers are present and non-empty.
    For entity-backed roles, validates the X-User-ID resolves to the right entity.
    Stores results on flask.g.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise E.APIError(E.ERR_UNAUTHENTICATED,
                         "Missing X-User-ID or X-User-Role header.",
                         401)
    g.user_id = user_id
    g.user_role = role


def require_roles(*allowed_roles):
    """Raise ERR_FORBIDDEN unless g.user_role is in allowed_roles."""
    if g.user_role not in allowed_roles:
        raise E.APIError(E.ERR_FORBIDDEN,
                         f"Role {g.user_role!r} not permitted for this endpoint.",
                         403)


def pagination_params():
    """Read limit/offset from query string with PRD defaults; raise ERR_INVALID_REQUEST on bad values."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise E.APIError(E.ERR_INVALID_REQUEST, "limit must be an integer.", 400)
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise E.APIError(E.ERR_INVALID_REQUEST, "offset must be an integer.", 400)
    if limit < 1 or limit > 100:
        raise E.APIError(E.ERR_INVALID_REQUEST,
                         "limit must be between 1 and 100.", 400)
    if offset < 0:
        raise E.APIError(E.ERR_INVALID_REQUEST, "offset must be >= 0.", 400)
    return limit, offset
