"""Pre-built role headers for the seven roles the PRD declares (§2.1).

Two roles are entity-backed. A `Consultant` caller's `X-User-ID` is the id of the
acting Consultant row; an `Applicant` caller's `X-User-ID` is the applicant's
email address. Ownership-gated calls MUST therefore use the per-instance builders
below rather than the shared constants, otherwise every row-level check rejects
the request.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_USER_ID,
    ANALYST_USER_ID,
    COMPLIANCE_USER_ID,
    COMPLIANCE_USER_ID_2,
    CONTROLLER_USER_ID,
    LEGAL_USER_ID,
)

TEST_USERS = {
    # Opaque operator identifiers — the canonical form for these five roles.
    "compliance_officer_headers": build_user_headers(COMPLIANCE_USER_ID, "ComplianceOfficer"),
    "compliance_officer_2_headers": build_user_headers(COMPLIANCE_USER_ID_2, "ComplianceOfficer"),
    "commission_analyst_headers": build_user_headers(ANALYST_USER_ID, "CommissionAnalyst"),
    "finance_controller_headers": build_user_headers(CONTROLLER_USER_ID, "FinanceController"),
    "legal_reviewer_headers": build_user_headers(LEGAL_USER_ID, "LegalReviewer"),
    "platform_admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    # Entity-backed roles — shared constants are for non-ownership tests only
    # (role rejection, shape rejection, not-found).
    "consultant_headers": build_user_headers("no-such-consultant", "Consultant"),
    "applicant_headers": build_user_headers("nobody@example.com", "Applicant"),
}


def make_consultant_headers(consultant_id: str) -> dict:
    """For the `Consultant` role: X-User-ID is the id of the acting Consultant row."""
    return build_user_headers(consultant_id, "Consultant")


def make_applicant_headers(applicant_email: str) -> dict:
    """For the `Applicant` role: X-User-ID is the applicant's email address."""
    return build_user_headers(applicant_email, "Applicant")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary user/role pairing — used to exercise the segregation-of-duties rule."""
    return build_user_headers(user_id, role)


ALL_ROLES = (
    "Applicant",
    "Consultant",
    "ComplianceOfficer",
    "CommissionAnalyst",
    "FinanceController",
    "LegalReviewer",
    "PlatformAdmin",
)
