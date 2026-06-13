"""Auth header extraction and role checking (PRD §2.1, §2.9)."""
from flask import request

import errors

KNOWN_ROLES = {"DispatchOperator", "Member", "ServiceProvider"}


class Identity:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_operator(self):
        return self.role == "DispatchOperator"

    @property
    def is_member(self):
        return self.role == "Member"

    @property
    def is_provider(self):
        return self.role == "ServiceProvider"


def authenticate():
    """Validate the two mandatory headers. Raise ERR_UNAUTHENTICATED if bad."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return Identity(user_id, role)


def require_roles(identity, allowed_roles):
    """ERR_FORBIDDEN_ROLE if the acting role is not in allowed_roles."""
    if identity.role not in allowed_roles:
        raise errors.forbidden_role()
