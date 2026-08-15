"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
# Passenger is entity_backed: the shared constant is a fallback for non-ownership
# tests only (e.g., RBAC-denial probes); ownership-gated calls MUST use
# make_passenger_headers(passenger["id"]).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "SystemAdmin"),
    "agent_headers": build_user_headers("test-agent-1", "BaggageServiceAgent"),
    "adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    "passenger_headers": build_user_headers("test-passenger-1", "Passenger"),
}


def make_passenger_headers(user_id: str) -> dict:
    """For Passenger (entity_backed:Passenger). Pass the actual Passenger.id as
    user_id whenever the call is ownership-gated (expense claim creation,
    accept/reject settlement)."""
    return build_user_headers(user_id, "Passenger")
