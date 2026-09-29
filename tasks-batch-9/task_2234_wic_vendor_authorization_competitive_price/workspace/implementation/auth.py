"""Authentication, RBAC and vendor scoping (PRD §2.1, ladder rules 1-3)."""

from flask import request

from config import ALL_ROLES, HEADER_USER_ID, HEADER_USER_ROLE, ROLE_VENDOR_OPERATOR
from errors import ApiError


class Caller:
    __slots__ = ("user_id", "role", "endpoint_roles")

    def __init__(self, user_id, role, endpoint_roles):
        self.user_id = user_id
        self.role = role
        self.endpoint_roles = endpoint_roles

    @property
    def is_vendor_operator(self):
        return self.role == ROLE_VENDOR_OPERATOR

    @property
    def vendor_scoped(self):
        """True when the ladder's rule 3 applies to this request."""
        return ROLE_VENDOR_OPERATOR in self.endpoint_roles and self.is_vendor_operator


def authenticate(*endpoint_roles):
    """Ladder rule 1 (401) then rule 2 (403)."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in endpoint_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return Caller(user_id, role, list(endpoint_roles))


def check_vendor_scope(caller, vendor_id):
    """Ladder rule 3: a VendorOperator may only address its own vendor."""
    if caller.vendor_scoped and vendor_id is not None and vendor_id != caller.user_id:
        raise ApiError("ERR_VENDOR_SCOPE_VIOLATION")
