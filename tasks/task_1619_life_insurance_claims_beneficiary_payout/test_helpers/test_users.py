"""Pre-built role headers for every role in the PRD.

PRD §2.1: for all six roles `X-User-ID` is an opaque operator identifier not
tied to any persisted entity. Segregation-of-duties checks (PRD §2.9) compare
the caller's `X-User-ID` against identifiers recorded on the claim or
document, so scenarios exercising those checks use the named per-user header
constants below (examiner-1 filed, examiner-2 reviews, approver-1 decides).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "claims_examiner_headers": build_user_headers("examiner-1", "ClaimsExaminer"),
    "claims_approver_headers": build_user_headers("approver-1", "ClaimsApprover"),
    "policy_administrator_headers": build_user_headers("policy-admin-1", "PolicyAdministrator"),
    "legal_counsel_headers": build_user_headers("legal-1", "LegalCounsel"),
    "compliance_officer_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    "system_admin_headers": build_user_headers("sysadmin-1", "SystemAdmin"),
}

# Named per-user headers used by segregation-of-duties scenarios (PRD §2.9).
EXAMINER_1 = TEST_USERS["claims_examiner_headers"]
EXAMINER_2 = build_user_headers("examiner-2", "ClaimsExaminer")
EXAMINER_3 = build_user_headers("examiner-3", "ClaimsExaminer")
APPROVER_1 = TEST_USERS["claims_approver_headers"]


def make_claims_examiner_headers(user_id: str) -> dict:
    """Per-user ClaimsExaminer headers — required whenever the scenario depends
    on which operator uploaded a document or filed a claim (PRD §2.9)."""
    return build_user_headers(user_id, "ClaimsExaminer")


def make_claims_approver_headers(user_id: str) -> dict:
    """Per-user ClaimsApprover headers — required when the approver's identity
    must equal (or differ from) the claim's assigned examiner (PRD §2.9)."""
    return build_user_headers(user_id, "ClaimsApprover")
