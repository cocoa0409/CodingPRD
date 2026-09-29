"""Authentication, role authorization and AgencyOwner scope (PRD 2.1, 2.11)."""

from flask import request

import errors
from errors import fail

ROLES = (
    "RecruitmentOfficer",
    "ComplianceOfficer",
    "AgencyOwner",
    "Registrar",
    "FinanceOfficer",
    "Applicant",
)


def authenticate():
    """Precedence group 1 - header presence and role recognition."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def authorize(role, allowed):
    """Precedence group 2 - role permitted for the endpoint / action variant."""
    if role not in allowed:
        fail(errors.ERR_UNAUTHORIZED, "Role %s is not permitted for this operation" % role)


def require_auth(allowed):
    user_id, role = authenticate()
    authorize(role, allowed)
    return user_id, role


def check_scope(role, user_id, agency_id):
    """Precedence group 3 - AgencyOwner may only act on its own agency."""
    if role != "AgencyOwner":
        return
    if agency_id is None:
        return
    if agency_id != user_id:
        fail(errors.ERR_AGENCY_SCOPE_VIOLATION,
             "AgencyOwner may only act on resources of its own agency")
