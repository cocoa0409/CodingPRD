"""Caller identities used by the suite.

Authentication is header based: ``X-User-ID`` carries the acting user and
``X-User-Role`` carries the role.  Five of the six roles are opaque — the
identifier is a free-form string and only the role decides what the caller
may do.  ``AgencyOwner`` is the exception: for that role the ``X-User-ID``
header must carry the identifier of the agency the caller owns, so owner
headers can only be built once the agency exists.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

ROLE_RECRUITMENT_OFFICER = "RecruitmentOfficer"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_FINANCE_OFFICER = "FinanceOfficer"
ROLE_REGISTRAR = "Registrar"
ROLE_AGENCY_OWNER = "AgencyOwner"
ROLE_APPLICANT = "Applicant"

# Opaque-identity callers.  Two distinct users exist for the roles that carry
# segregation-of-duties obligations (compliance countersignature, and the
# approve/pay split on the commission ledger).
TEST_USERS: Dict[str, Dict[str, str]] = {
    "officer_1": build_user_headers("officer-1", ROLE_RECRUITMENT_OFFICER),
    "officer_2": build_user_headers("officer-2", ROLE_RECRUITMENT_OFFICER),
    "officer_7": build_user_headers("officer-7", ROLE_RECRUITMENT_OFFICER),
    "compliance_1": build_user_headers("compliance-1", ROLE_COMPLIANCE_OFFICER),
    "compliance_2": build_user_headers("compliance-2", ROLE_COMPLIANCE_OFFICER),
    "finance_1": build_user_headers("finance-1", ROLE_FINANCE_OFFICER),
    "finance_2": build_user_headers("finance-2", ROLE_FINANCE_OFFICER),
    "registrar_1": build_user_headers("registrar-1", ROLE_REGISTRAR),
    # A single human wearing two hats: drafts a contract as a recruitment
    # officer and then attempts the compliance countersignature.
    "dual_hat_officer": build_user_headers("dual-hat-1", ROLE_RECRUITMENT_OFFICER),
    "dual_hat_compliance": build_user_headers("dual-hat-1", ROLE_COMPLIANCE_OFFICER),
}

# Convenience aliases for the most frequently used callers.
OFFICER = TEST_USERS["officer_1"]
COMPLIANCE = TEST_USERS["compliance_1"]
COMPLIANCE_COUNTERSIGNER = TEST_USERS["compliance_2"]
FINANCE_APPROVER = TEST_USERS["finance_1"]
FINANCE_PAYER = TEST_USERS["finance_2"]
REGISTRAR = TEST_USERS["registrar_1"]

# A caller that supplies a role but no user identifier at all.
HEADERS_WITHOUT_USER_ID: Dict[str, str] = {
    "X-User-Role": ROLE_RECRUITMENT_OFFICER,
    "Content-Type": "application/json",
}

# A caller whose role string is not one of the six recognised roles.
HEADERS_WITH_UNKNOWN_ROLE: Dict[str, str] = build_user_headers(
    "officer-1", "SuperAdmin"
)


def make_agency_owner_headers(agency_id: str) -> Dict[str, str]:
    """Build ``AgencyOwner`` headers whose user identifier is the agency id.

    Every ownership-scoped call must be made with the identifier of the agency
    that actually owns the resource; passing a different agency's id is what
    produces a scope violation rather than a plain authorization failure.
    """
    return build_user_headers(agency_id, ROLE_AGENCY_OWNER)


def make_applicant_headers(applicant_user_id: str) -> Dict[str, str]:
    """Build ``Applicant`` headers for the prospective student.

    The applicant identifier is opaque; the acknowledgement token issued with
    the disclosure, not the identifier, is what authorises the acknowledgement.
    """
    return build_user_headers(applicant_user_id, ROLE_APPLICANT)


def make_officer_headers(user_id: str) -> Dict[str, str]:
    """Build ``RecruitmentOfficer`` headers for a specific opaque user id."""
    return build_user_headers(user_id, ROLE_RECRUITMENT_OFFICER)


def make_compliance_headers(user_id: str) -> Dict[str, str]:
    """Build ``ComplianceOfficer`` headers for a specific opaque user id."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_finance_headers(user_id: str) -> Dict[str, str]:
    """Build ``FinanceOfficer`` headers for a specific opaque user id."""
    return build_user_headers(user_id, ROLE_FINANCE_OFFICER)


def make_registrar_headers(user_id: str) -> Dict[str, str]:
    """Build ``Registrar`` headers for a specific opaque user id."""
    return build_user_headers(user_id, ROLE_REGISTRAR)
