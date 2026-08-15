"""Auth context: X-User-ID / X-User-Role headers, role gating (PRD 2.1)."""
from flask import request

from errors import raise_err

ROLES = {"Borrower", "LoanOfficer", "CreditCommittee",
         "InsuranceAdjuster", "AssociationBoard", "System"}

ALL_ROLES = ["Borrower", "LoanOfficer", "CreditCommittee",
             "InsuranceAdjuster", "AssociationBoard", "System"]


def auth():
    """Tier 1: context headers present and role declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID and a declared X-User-Role header are required")
    return uid, role


def require_role(role, allowed):
    """Tier 2: caller role listed for the endpoint."""
    if role not in allowed:
        raise_err("ERR_FORBIDDEN_FOR_ROLE",
                  "Role %s is not permitted for this endpoint" % role)


def require_owner(condition):
    """Tier 3: borrower ownership of the target resource chain."""
    if not condition:
        raise_err("ERR_RESOURCE_NOT_OWNED",
                  "Borrower caller does not own the target resource")
