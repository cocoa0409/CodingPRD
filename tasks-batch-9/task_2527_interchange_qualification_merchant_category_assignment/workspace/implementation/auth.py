"""Authentication, role authorisation and AcquirerOps ownership scoping.

Header names and role values come from PRD section 2.1 and the scaffold's
auth validations: X-User-ID plus X-User-Role over five role names.
"""

from flask import request

from errors import (
    ERR_ACQUIRER_SCOPE_VIOLATION,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    fail,
)
from store import ROLES

ALL_ROLES = list(ROLES)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_acquirer_ops(self):
        return self.role == "AcquirerOps"


def authenticate(allowed_roles):
    """Priority 1 then priority 2 of the rejection ladder (PRD section 2.9)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail(ERR_UNAUTHENTICATED)
    if role not in allowed_roles:
        fail(ERR_UNAUTHORIZED)
    return Caller(user_id, role)


def require_scope(caller, owner_acquirer_id):
    """Priority 6: an AcquirerOps caller's X-User-ID must be the owning acquirer."""
    if not caller.is_acquirer_ops:
        return
    if owner_acquirer_id is None or owner_acquirer_id != caller.user_id:
        fail(ERR_ACQUIRER_SCOPE_VIOLATION)
