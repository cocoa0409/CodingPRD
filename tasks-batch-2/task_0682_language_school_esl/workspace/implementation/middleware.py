"""Auth + RBAC (PRD §2.1, §2.8).

Headers: X-User-ID and X-User-Role. Roles spelled exactly:
Registrar, DSO, Instructor, Student, CorporateSponsor, Anonymous.
"""
from flask import request

import errors

VALID_ROLES = {"Registrar", "DSO", "Instructor", "Student", "CorporateSponsor", "Anonymous"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allow_anonymous):
    """Extract and validate the X-User-ID / X-User-Role headers.

    PRD §2.1: a request missing either header, or supplying a malformed value, on
    an endpoint that requires authentication is rejected with ERR_UNAUTHENTICATED.

    `allow_anonymous` is True only for the self-register and placement-test-register
    endpoints, where an unauthenticated public caller is permitted.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if allow_anonymous:
        # Public endpoints: when no auth headers are present at all, treat the caller
        # as Anonymous. When headers ARE supplied they must be well-formed.
        if user_id is None and role is None:
            return Caller(None, "Anonymous")

    if user_id is None or role is None or user_id == "" or role == "" or role not in VALID_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or malformed authentication headers")

    return Caller(user_id, role)


def require_roles(caller, allowed_roles):
    """PRD §2.1: well-formed but not-permitted role -> ERR_FORBIDDEN (403)."""
    if caller.role not in allowed_roles:
        raise errors.err(errors.ERR_FORBIDDEN, "Role not permitted for this endpoint")
