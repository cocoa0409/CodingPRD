"""Auth header extraction and role checking.

PRD §2.1: every request carries two mandatory headers, X-User-ID and X-User-Role.
A missing or malformed value -> ERR_UNAUTHENTICATED. The four recognised roles are
Publisher, Advertiser, Listener, PlatformAdmin. A well-authenticated caller whose
role may not perform the operation -> ERR_FORBIDDEN.
"""

from flask import request

import errors
from db import ROLES


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate the two auth headers and return a Caller.

    Raises ERR_UNAUTHENTICATED when either header is missing/blank or the role
    value is not one of the four recognised roles (PRD §2.1: a malformed value
    is rejected as unauthenticated).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing authentication headers")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Blank authentication header")
    if role not in ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Unknown role")
    return Caller(user_id, role)


def require_role(caller, allowed_roles):
    """ERR_FORBIDDEN when the caller's role is not in the allowed set (PRD §2.1)."""
    if caller.role not in allowed_roles:
        raise errors.err(errors.ERR_FORBIDDEN, "Role not permitted for this operation")
