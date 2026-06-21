"""Auth header extraction and role checking (PRD §2.1, scaffold §1.4, §1.7).

Headers: X-User-ID (acting user / Account.id for Subscriber), X-User-Role
(one of Subscriber, MonitoringOperator, Administrator).
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {"Subscriber", "MonitoringOperator", "Administrator"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate the two mandatory headers. Raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise err(ERR_UNAUTHENTICATED, "Empty X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Unrecognized X-User-Role value")
    return Caller(user_id, role)


def require_role(caller, allowed_roles):
    """RBAC: raises ERR_FORBIDDEN when caller.role is not in allowed_roles."""
    if caller.role not in allowed_roles:
        raise err(ERR_FORBIDDEN, "Role %s is not permitted for this operation" % caller.role)
