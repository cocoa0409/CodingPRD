"""Pre-built role headers for every role in the PRD (§2.1).

Identity model (PRD §2.1): RemediationOwner's X-User-ID is the acting
BankOfficer's id; ComplianceReviewer's X-User-ID is the acting
ComplianceReviewer's id. The other three roles carry opaque operator ids.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles, and for entity-backed roles in
# tests that never exercise an ownership-gated comparison.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "ram_headers": build_user_headers("test-ram-1", "RegulatoryAffairsManager"),
    "board_reporter_headers": build_user_headers("test-board-reporter-1", "BoardReporter"),
    # Fallback only for non-ownership calls (e.g. 400/404/role-check tests).
    "remediation_owner_headers": build_user_headers("test-owner-1", "RemediationOwner"),
    "compliance_reviewer_headers": build_user_headers("test-reviewer-1", "ComplianceReviewer"),
}


def make_remediation_owner_headers(user_id: str) -> dict:
    """RemediationOwner is entity-backed by BankOfficer: pass the officer's id
    whenever the call records or compares ownership (plans, evidence,
    submissions, validation)."""
    return build_user_headers(user_id, "RemediationOwner")


def make_compliance_reviewer_headers(user_id: str) -> dict:
    """ComplianceReviewer is entity-backed by ComplianceReviewer: pass the
    reviewer's id whenever the call records reviewed_by_user_id or evaluates
    segregation of duties / certification."""
    return build_user_headers(user_id, "ComplianceReviewer")
