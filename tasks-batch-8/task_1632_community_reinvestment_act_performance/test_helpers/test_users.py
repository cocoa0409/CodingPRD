"""Pre-built role headers for every role in PRD §2.1.

All six roles have opaque identity: per PRD §2.1, `X-User-ID` "is an opaque
operator identifier that is not tied to any persisted entity". The shared
constants below are therefore safe for every call. The per-user builders exist
because the segregation-of-duties check of PRD §3.4 compares the reviewer's
`X-User-ID` against the activity's recorded `submitted_by_user_id`, so tests
must control those two ids precisely.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "cra_officer_headers": build_user_headers("officer-1", "CRAOfficer"),
    "compliance_analyst_headers": build_user_headers("analyst-1", "ComplianceAnalyst"),
    "qualification_reviewer_headers": build_user_headers("reviewer-1", "QualificationReviewer"),
    "bank_examiner_headers": build_user_headers("examiner-1", "BankExaminer"),
    "bank_executive_headers": build_user_headers("executive-1", "BankExecutive"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
}

# Auth-negative probes (PRD §2.1): a well-formed request missing the role/id headers.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
UNDEFINED_ROLE_HEADERS = {
    "X-User-ID": "intruder-1",
    "X-User-Role": "SuperUser",
    "Content-Type": "application/json",
}


def make_cra_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CRAOfficer")


def make_compliance_analyst_headers(user_id: str) -> dict:
    """ComplianceAnalyst identity is recorded as submitted_by_user_id on CD
    activities (PRD §3.4); control it for segregation-of-duties tests."""
    return build_user_headers(user_id, "ComplianceAnalyst")


def make_qualification_reviewer_headers(user_id: str) -> dict:
    """QualificationReviewer identity is recorded as reviewed_by_user_id (PRD
    §3.4); control it for segregation-of-duties tests."""
    return build_user_headers(user_id, "QualificationReviewer")


def make_bank_examiner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BankExaminer")


def make_bank_executive_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BankExecutive")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
