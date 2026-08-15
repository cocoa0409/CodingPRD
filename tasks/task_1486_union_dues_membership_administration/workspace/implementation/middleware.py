"""Auth context: X-User-ID / X-User-Role extraction, role gating, Member ownership."""
import functools

from flask import request

import errors

ROLES = {"ParentBodyAdmin", "LocalAdmin", "SecretaryTreasurer", "OfficeClerk", "Member"}
ALL_ROLES = tuple(sorted(ROLES))


def context():
    """Validate the two auth headers and return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.missing_context()
    return user_id, role


def require_roles(*roles):
    """Decorator: enforces header presence (400) then role permission (403)."""
    def wrapper(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            user_id, role = context()
            if role not in roles:
                raise errors.insufficient_permissions()
            return fn(user_id, role, *args, **kwargs)
        return inner
    return wrapper


def check_member_ownership(user_id, role, member_id):
    """Member-role callers may only act on resources whose member FK == X-User-ID."""
    if role == "Member" and user_id != member_id:
        raise errors.not_resource_owner()
