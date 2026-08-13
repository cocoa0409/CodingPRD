"""Auth header extraction and role checks (PRD section 2.1).

Every request must carry X-User-ID and X-User-Role, both non-empty,
else ERR_UNAUTHENTICATED (401). Role not on the endpoint's list ->
ERR_UNAUTHORIZED (403). ParticipantRepresentative is entity-backed:
X-User-ID is the acting Participant's id.
"""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLE_ACO_ADMIN = "AcoAdministrator"
ROLE_CLAIMS = "ClaimsProcessor"
ROLE_REPORTER = "QualityReporter"
ROLE_AUDITOR = "QualityAuditor"
ROLE_ACTUARY = "SettlementActuary"
ROLE_APPROVER = "DistributionApprover"
ROLE_MRO = "MedicalReviewOfficer"
ROLE_APPEALS = "AppealsOfficer"
ROLE_PR = "ParticipantRepresentative"
ROLE_PLATFORM = "PlatformAdmin"

ALL_DOMAIN_ROLES = [
    ROLE_ACO_ADMIN, ROLE_CLAIMS, ROLE_REPORTER, ROLE_AUDITOR, ROLE_ACTUARY,
    ROLE_APPROVER, ROLE_MRO, ROLE_APPEALS, ROLE_PR,
]


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise ApiError(
            ERR_UNAUTHENTICATED, 401,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    return uid, role


def require_roles(allowed):
    uid, role = authenticate()
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED, 403, "Role is not authorized for this endpoint")
    return uid, role
