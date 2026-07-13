"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Harbormaster, FinanceClerk) and for
# tests that do not exercise Boater ownership.
TEST_USERS = {
    "harbormaster_headers": build_user_headers("test-harbormaster-1", "Harbormaster"),
    "finance_clerk_headers": build_user_headers("test-finance-1", "FinanceClerk"),
    # Boater is entity_backed: this shared constant is a fallback for non-ownership
    # tests only (e.g. 401/validation). Ownership-gated calls MUST use the builder.
    "boater_headers": build_user_headers("test-boater-1", "Boater"),
}


def make_boater_headers(user_id: str) -> dict:
    """For Boater (entity_backed:Boater). Pass the acting Boater.id as user_id
    whenever the call is ownership-gated (paying/cancelling an owned resource)."""
    return build_user_headers(user_id, "Boater")


def make_harbormaster_headers(user_id: str = "test-harbormaster-1") -> dict:
    return build_user_headers(user_id, "Harbormaster")
