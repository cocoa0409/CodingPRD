"""Auth header extraction and role checks (PRD §2.1, §2.10).

Headers: X-User-ID (acting principal), X-User-Role (capacity).
Roles (exact spelling, PRD §2.1):
  Anonymous, ProgramAdmin, Claimant, Adjudicator, BenefitPaymentOfficer,
  Employer, AppealsClerk, Referee.
"""
from flask import request

from errors import err

ROLES = {
    "Anonymous",
    "ProgramAdmin",
    "Claimant",
    "Adjudicator",
    "BenefitPaymentOfficer",
    "Employer",
    "AppealsClerk",
    "Referee",
}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allow_anonymous=False):
    """Validate presence of X-User-ID and X-User-Role.

    Returns a Principal. Raises ERR_UNAUTHENTICATED (401) when either header
    is missing/blank or the role is not a recognized role.

    `allow_anonymous` only affects role-permission checks downstream; both
    headers must still be present here. For anonymous-permitted creates the
    caller may pass X-User-Role: Anonymous.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header.")
    if role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unknown X-User-Role.")
    return Principal(user_id, role)


def require_role(principal, allowed_roles):
    """Raise ERR_FORBIDDEN_ROLE (403) if principal.role not permitted."""
    if principal.role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE",
                  "Role %s is not permitted for this operation." % principal.role)
