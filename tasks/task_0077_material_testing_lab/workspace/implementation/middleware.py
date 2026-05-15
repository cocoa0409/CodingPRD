"""Auth middleware: validates X-User-ID and X-User-Role headers and RBAC."""

from functools import wraps
from flask import request, g

from errors import (
    APIError,
    ERR_AUTH_MISSING,
    ERR_AUTH_INVALID,
    ERR_FORBIDDEN,
    raise_error,
)


VALID_ROLES = {
    "LabClerk",
    "Tester",
    "Reviewer",
    "Signatory",
    "LabManager",
}


def _check_auth_headers(skip_presence_check: bool = False):
    """Validate X-User-ID and X-User-Role. Returns (user_id, user_role).

    Per PRD §2.1: presence check then role validity check. /_clock/advance
    and /_events/emit skip the presence check (operator-mode), but the
    scaffold also lists those endpoints as LabManager-only — so callers in
    practice must still supply LabManager headers if they want full audit
    fields. We still always read whatever headers are present.
    """
    user_id = request.headers.get("X-User-ID", "")
    user_role = request.headers.get("X-User-Role", "")
    if not skip_presence_check:
        if not user_id or not user_role:
            raise_error(ERR_AUTH_MISSING, "Missing X-User-ID or X-User-Role")
    if user_role and user_role not in VALID_ROLES:
        raise_error(ERR_AUTH_INVALID, f"Unknown role: {user_role}")
    return user_id, user_role


def auth_required(allowed_roles, skip_presence_check: bool = False):
    """Decorator: validates auth headers and RBAC.

    `allowed_roles` is a list of role names. If empty, only auth-header
    validity is checked. If skip_presence_check is True (admin endpoints),
    the presence rule (ERR_AUTH_MISSING) is not enforced but role validity
    is still checked when a role is supplied.
    """
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    allowed_set = set(allowed_roles or [])

    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user_id, user_role = _check_auth_headers(skip_presence_check=skip_presence_check)
            if allowed_set and user_role not in allowed_set:
                raise_error(ERR_FORBIDDEN, f"Role {user_role!r} not permitted")
            g.user_id = user_id
            g.user_role = user_role
            return fn(*args, **kwargs)
        return wrapped
    return deco
