"""Pre-built role headers for every role in the PRD (§2.1).

All six roles use opaque X-User-ID identifiers (never matched against a
persisted entity's id), so shared constants are the canonical form. The
make_* builders exist for segregation-of-duties scenarios (PRD §3.4) that
need the decider's X-User-ID to equal — or differ from — a proposer's.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "comp_analyst_headers": build_user_headers("user-analyst-1", "CompAnalyst"),
    "legal_counsel_headers": build_user_headers("user-counsel-1", "LegalCounsel"),
    "remediation_approver_headers": build_user_headers("user-approver-1", "RemediationApprover"),
    "people_ops_admin_headers": build_user_headers("user-peopleops-1", "PeopleOpsAdmin"),
    "compliance_reporter_headers": build_user_headers("user-reporter-1", "ComplianceReporter"),
    "platform_admin_headers": build_user_headers("user-admin-1", "PlatformAdmin"),
}


def make_comp_analyst_headers(user_id: str) -> dict:
    """CompAnalyst headers with a specific X-User-ID (proposer attribution)."""
    return build_user_headers(user_id, "CompAnalyst")


def make_legal_counsel_headers(user_id: str) -> dict:
    """LegalCounsel headers with a specific X-User-ID."""
    return build_user_headers(user_id, "LegalCounsel")


def make_remediation_approver_headers(user_id: str) -> dict:
    """RemediationApprover headers with a specific X-User-ID (decider attribution)."""
    return build_user_headers(user_id, "RemediationApprover")


def make_people_ops_admin_headers(user_id: str) -> dict:
    """PeopleOpsAdmin headers with a specific X-User-ID."""
    return build_user_headers(user_id, "PeopleOpsAdmin")


def make_compliance_reporter_headers(user_id: str) -> dict:
    """ComplianceReporter headers with a specific X-User-ID."""
    return build_user_headers(user_id, "ComplianceReporter")


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin headers with a specific X-User-ID."""
    return build_user_headers(user_id, "PlatformAdmin")
