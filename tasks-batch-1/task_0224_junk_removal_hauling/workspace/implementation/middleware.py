"""Auth header extraction and role checking.

Headers (PRD §2.1): X-User-ID and X-User-Role. Five roles:
PlatformAdmin, Customer, Dispatcher, CrewLead, Billing.
"""
from flask import request
import errors
from errors import err

KNOWN_ROLES = {"PlatformAdmin", "Customer", "Dispatcher", "CrewLead", "Billing"}


class Auth(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Priority 1: both headers present and role known, else ERR_MISSING_OR_INVALID_AUTH."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        err(errors.ERR_MISSING_OR_INVALID_AUTH,
            "X-User-ID and X-User-Role headers required and role must be known")
    return Auth(user_id, role)


def require_role(auth, allowed_roles):
    """Priority 2 (role part): role must be in the allowed set, else ERR_FORBIDDEN_ROLE."""
    if auth.role not in allowed_roles:
        err(errors.ERR_FORBIDDEN_ROLE,
            "Role %s is not permitted for this operation" % auth.role)
