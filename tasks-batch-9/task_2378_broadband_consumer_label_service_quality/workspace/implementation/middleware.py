"""Authentication, authorisation and Subscriber scoping (PRD §2.1, §2.11)."""

from flask import request

import errors
from errors import fail

COMPLIANCE_OFFICER = "ComplianceOfficer"
NETWORK_ENGINEER = "NetworkEngineer"
LOCALIZATION_SPECIALIST = "LocalizationSpecialist"
COMPLAINT_ANALYST = "ComplaintAnalyst"
REGULATORY_LIAISON = "RegulatoryLiaison"
RETAIL_AGENT = "RetailAgent"
SUBSCRIBER = "Subscriber"

ALL_ROLES = (
    COMPLIANCE_OFFICER,
    NETWORK_ENGINEER,
    LOCALIZATION_SPECIALIST,
    COMPLAINT_ANALYST,
    REGULATORY_LIAISON,
    RETAIL_AGENT,
    SUBSCRIBER,
)


class Principal(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_subscriber(self):
        return self.role == SUBSCRIBER


def authorize(*allowed_roles):
    """Ladder steps 1 and 2: authentication then authorisation."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        fail(errors.ERR_UNAUTHENTICATED)
    if allowed_roles and role not in allowed_roles:
        fail(errors.ERR_UNAUTHORIZED)
    return Principal(user_id, role)


def require_own_account(principal, account_id):
    """Ladder step 5 — Subscriber scope (PRD §2.1)."""
    if principal.is_subscriber and account_id != principal.user_id:
        fail(errors.ERR_ACCOUNT_SCOPE_VIOLATION)
