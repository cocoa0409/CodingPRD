"""Auth context and RBAC (PRD 2.1, scaffold validations 1-3, roles table).

Headers: X-User-ID and X-User-Role. Five role names spelled exactly:
CIO, Analyst, InvestmentCommittee, OperationsAnalyst, ComplianceOfficer.
Entity-backed roles (Analyst / InvestmentCommittee / OperationsAnalyst)
resolve X-User-ID against a StaffUser row whose staff_role matches;
CIO and ComplianceOfficer are opaque.
"""

from flask import request

import db
from errors import raise_err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {"CIO", "Analyst", "InvestmentCommittee", "OperationsAnalyst", "ComplianceOfficer"}

ALL_ROLES = ["CIO", "Analyst", "InvestmentCommittee", "OperationsAnalyst", "ComplianceOfficer"]

ENTITY_BACKED = {
    "Analyst": "ANALYST",
    "InvestmentCommittee": "IC_MEMBER",
    "OperationsAnalyst": "OPS_ANALYST",
}


def auth_context():
    """Validation priority 1-2: role header present and recognized; X-User-ID
    present for every role, and resolved against StaffUser for entity-backed
    roles."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED,
                  "X-User-Role header must name a declared role")
    if not user_id:
        raise_err(ERR_UNAUTHENTICATED,
                  "X-User-ID header is required")
    if role in ENTITY_BACKED:
        staff = db.STORE.staff_users.get(user_id)
        if staff is None or staff.get("staff_role") != ENTITY_BACKED[role]:
            raise_err(ERR_UNAUTHENTICATED,
                      "X-User-ID must identify a StaffUser with the matching staff_role")
    return user_id, role


def require_role(role, allowed):
    """Validation priority 3: role permitted for the endpoint."""
    if role not in allowed:
        raise_err(ERR_UNAUTHORIZED,
                  "Role %s is not permitted for this endpoint" % role)
