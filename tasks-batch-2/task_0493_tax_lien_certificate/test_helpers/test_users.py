"""Pre-built role headers for every role in the PRD (§2.1).

The Investor role is entity_backed: X-User-ID must equal the acting Investor's
id for ownership checks (bids, sub-taxes, assignments, deed applications). Use
make_investor_headers(investor_id) whenever the call is ownership-gated.

CountyTreasurer and Auditor are opaque roles whose X-User-ID is not tied to any
entity, so the shared constant is the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# Investor ownership (e.g. 400/404/403-by-role cases).
TEST_USERS = {
    "treasurer_headers": build_user_headers("test-treasurer-1", "CountyTreasurer"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # Fallback only for non-ownership Investor tests (e.g. role-denied checks
    # that never reach an ownership comparison).
    "investor_headers": build_user_headers("test-investor-1", "Investor"),
}


def make_investor_headers(user_id: str) -> dict:
    """For the Investor role (entity_backed:Investor). Pass the actual
    Investor.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Investor")


def make_treasurer_headers(user_id: str) -> dict:
    """For CountyTreasurer with a specific opaque operator id. Used by the
    segregation-of-duties path where the treasurer's X-User-ID is compared
    against winning bidders."""
    return build_user_headers(user_id, "CountyTreasurer")
