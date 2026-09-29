"""Auth header extraction and RBAC (PRD 2.1, gates 1-2 of PRD 2.5)."""

from flask import request

import errors
from errors import fail

ROLES = ("PlatformAdmin", "Coordinator", "Cleaner", "QualityAuditor", "PropertyOwner")


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_cleaner(self):
        return self.role == "Cleaner"

    @property
    def is_owner(self):
        return self.role == "PropertyOwner"


def authenticate(allowed_roles):
    """Gate 1 (401) then gate 2 (403)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "" or role is None or role not in ROLES:
        fail(errors.ERR_UNAUTHENTICATED)
    if role not in allowed_roles:
        fail(errors.ERR_UNAUTHORIZED)
    return Actor(str(user_id), role)
