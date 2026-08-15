"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. Producer is entity-backed: ownership-gated calls MUST use
# make_producer_headers(producer["id"]) instead of the shared fallback.
TEST_USERS = {
    "carrier_admin_headers": build_user_headers("test-admin-1", "CarrierAdmin"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "producer_headers": build_user_headers("test-producer-1", "Producer"),
    "reviewer_headers": build_user_headers("rev-1", "SuitabilityReviewer"),
    "principal_headers": build_user_headers("prin-1", "Principal"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "ops_headers": build_user_headers("test-ops-1", "OperationsDesk"),
}


def make_producer_headers(user_id: str) -> dict:
    """For Producer (entity-backed by the Producer record). Pass the actual
    Producer.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Producer")


def make_reviewer_headers(user_id: str) -> dict:
    """SuitabilityReviewer with a specific opaque operator id (e.g. when the
    same identity must reappear as reviewed_by_id or in a duty-segregation
    probe)."""
    return build_user_headers(user_id, "SuitabilityReviewer")


def make_principal_headers(user_id: str) -> dict:
    """Principal with a specific opaque operator id."""
    return build_user_headers(user_id, "Principal")
