"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "Coordinator"),
    "funder_admin_headers": build_user_headers("test-funder-admin-1", "FunderAdmin"),
    # entity_backed roles: fallback for non-ownership tests ONLY.
    "caregiver_headers": build_user_headers("test-caregiver-1", "Caregiver"),
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
}


def make_caregiver_headers(user_id: str) -> dict:
    """For Caregiver (entity_backed). Pass the actual Caregiver.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Caregiver")


def make_provider_headers(user_id: str) -> dict:
    """For Provider (entity_backed). Pass the actual Provider.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Provider")
