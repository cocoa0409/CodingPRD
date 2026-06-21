"""Auth header extraction and RBAC checking.

Auth headers (PRD §2.1, SCAFFOLD validations[priority=1]):
  X-User-ID    identifying principal (Customer.id when role==Customer; opaque otherwise)
  X-User-Role  one of: BureauAdmin, Customer, Operator, QAReviewer
"""

from flask import request

import errors

ROLES = {"BureauAdmin", "Customer", "Operator", "QAReviewer"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_auth():
    """Validate the two mandatory auth headers.

    Returns a Principal. Raises ERR_UNAUTHENTICATED (401) when either header
    is missing/blank, per validation priority 1.

    Note: an unrecognized role string is NOT an authentication failure here;
    it simply won't match any endpoint's authorized-role list and so will be
    rejected as ERR_FORBIDDEN at the authorization stage (priority 2).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.unauthenticated()
    return Principal(user_id, role)


def require_role(principal, allowed_roles):
    """Authorization (priority 2): the acting role must be permitted."""
    if principal.role not in allowed_roles:
        raise errors.forbidden()
