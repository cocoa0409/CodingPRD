"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request, g

from errors import ApiError, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_INSUFFICIENT_PERMISSIONS

ROLES = {
    "BankAdmin",
    "RelationshipManager",
    "CreditAnalyst",
    "AppraisalManager",
    "CommitteeChair",
    "CommitteeMember",
    "CreditPolicyOfficer",
    "CreditAdministrator",
}

ALL_ROLES = sorted(ROLES)


def authenticate():
    """Pipeline stage 1: header presence + recognized role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER[0],
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER[1],
            "X-User-ID and X-User-Role headers are required and the role must be recognized.",
        )
    g.user_id = user_id
    g.user_role = role


def require_roles(*roles):
    """Pipeline stage 2: endpoint-level role permission."""
    if g.user_role not in roles:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS[0],
            ERR_INSUFFICIENT_PERMISSIONS[1],
            "Role %s is not permitted to perform this operation." % g.user_role,
        )
