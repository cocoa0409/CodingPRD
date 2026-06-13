"""Auth header extraction, role checking, and request-parsing helpers.

PRD §2.1: every request carries X-User-ID and X-User-Role. Valid roles are
exactly Customer, Attorney, PlatformAdmin. Missing/unknown role -> 401
(ERR_UNAUTHENTICATED). Known role not permitted for the operation -> 403
(ERR_FORBIDDEN_ROLE). Auth precedes authorization precedes everything else.
"""

from functools import wraps

from flask import request

import errors

VALID_ROLES = {"Customer", "Attorney", "PlatformAdmin"}


def get_role():
    return request.headers.get("X-User-Role")


def get_user_id():
    return request.headers.get("X-User-ID")


def require_auth():
    """Validate the role header. Returns the role string or raises 401."""
    role = get_role()
    if role is None or role not in VALID_ROLES:
        raise errors.unauthenticated()
    return role


def require_roles(*allowed):
    """Auth (401) then role authorization (403)."""
    role = require_auth()
    if role not in allowed:
        raise errors.forbidden()
    return role


def roles(*allowed):
    """Decorator: enforce auth + role for a route, before any other logic."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            require_roles(*allowed)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def get_json_body():
    """Parse the JSON body; missing/invalid body -> empty dict (treated as
    missing required fields downstream -> ERR_INVALID_REQUEST)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None or not isinstance(body, dict):
        return {}
    return body


def parse_pagination():
    """Read limit/offset query params with defaults/clamps from §1.0.

    limit default 10, min 1, max 100; offset default 0 (min 0).
    Malformed values raise ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            offset = 0

    return limit, offset
