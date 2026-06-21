"""Pre-built role headers for every role in the PRD (Section 2.1).

All five roles use an OPAQUE identity model: X-User-ID is never compared to
any entity's id for ownership (PRD §2.1). The shared constants below are
therefore safe everywhere.

The one place X-User-ID is semantically load-bearing is the four-eyes
segregation check: classification records `classified_by_user_id` and
announcement records `approved_by_user_id`, and the two MUST differ
(PRD §3.6). For that the suite needs DISTINCT user ids under the same or
different roles — `make_headers(user_id, role)` builds those on demand, and
the *_ALT constants provide a second distinct identity for the roles that
participate in segregation.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "recall_coordinator_headers": build_user_headers("user-coordinator-1", "RecallCoordinator"),
    "quality_officer_headers": build_user_headers("user-officer-1", "QualityOfficer"),
    "field_service_agent_headers": build_user_headers("user-agent-1", "FieldServiceAgent"),
    "finance_clerk_headers": build_user_headers("user-clerk-1", "FinanceClerk"),
    "platform_admin_headers": build_user_headers("user-admin-1", "PlatformAdmin"),
    # Second distinct identities for the four-eyes segregation workflow.
    "recall_coordinator_headers_alt": build_user_headers("user-coordinator-2", "RecallCoordinator"),
    "quality_officer_headers_alt": build_user_headers("user-officer-2", "QualityOfficer"),
}


def make_headers(user_id: str, role: str) -> dict:
    """Build headers for an explicit (user_id, role) pair.

    Used wherever the test must control the acting X-User-ID — chiefly the
    four-eyes segregation tests, where the classifying coordinator and the
    announcing officer (or a re-announcing user) must carry specific,
    distinct identities.
    """
    return build_user_headers(user_id, role)
