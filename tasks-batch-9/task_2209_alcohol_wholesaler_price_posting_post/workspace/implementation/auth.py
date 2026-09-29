"""Authentication, role authorisation and wholesaler-scope checks.

Priorities 1, 2 and 6 of the PRD section 2.10 rejection ladder.
"""

from flask import request

from errors import raise_err
from store import db

ROLE_FILING_AGENT = "FilingAgent"
ROLE_CERTIFYING_OFFICER = "CertifyingOfficer"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"

KNOWN_ROLES = (ROLE_FILING_AGENT, ROLE_CERTIFYING_OFFICER, ROLE_COMPLIANCE_OFFICER)
ALL_ROLES = list(KNOWN_ROLES)

# The two entity-backed roles and the LicenseeUser.user_role values that satisfy them.
ENTITY_BACKED = {
    ROLE_FILING_AGENT: ("FILING_AGENT", "DUAL_ROLE"),
    ROLE_CERTIFYING_OFFICER: ("CERTIFYING_OFFICER", "DUAL_ROLE"),
}

ROLE_HEADER = "X-User-Role"
USER_HEADER = "X-User-ID"


class Actor:
    def __init__(self, role, user_id, user):
        self.role = role
        self.user_id = user_id
        self.user = user

    @property
    def is_entity_backed(self):
        return self.user is not None

    @property
    def wholesaler_id(self):
        return self.user["wholesaler_id"] if self.user else None


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def authenticate(allowed_roles):
    """Resolve the acting identity, enforcing priorities 1 and 2."""
    role = _header(ROLE_HEADER)
    # Priority 1 -- authentication.
    if role is None or role not in KNOWN_ROLES:
        raise_err("ERR_UNAUTHENTICATED")
    user_id = _header(USER_HEADER)
    if role in ENTITY_BACKED and user_id is None:
        raise_err("ERR_UNAUTHENTICATED")

    # Priority 2 -- role authorisation.
    if role not in allowed_roles:
        raise_err("ERR_UNAUTHORIZED")
    user = None
    if role in ENTITY_BACKED:
        user = db.licensee_users.get(user_id)
        if user is None:
            raise_err("ERR_UNAUTHORIZED")
        if not user.get("is_active"):
            raise_err("ERR_UNAUTHORIZED")
        if user.get("user_role") not in ENTITY_BACKED[role]:
            raise_err("ERR_UNAUTHORIZED")
    return Actor(role, user_id, user)


def require_scope(actor, wholesaler_id):
    """Priority 6 -- an entity-backed role may only act inside its own wholesaler."""
    if actor.user is None:
        return
    if actor.user.get("wholesaler_id") != wholesaler_id:
        raise_err("ERR_FORBIDDEN_WHOLESALER_SCOPE")
