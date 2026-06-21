"""Pre-built role headers for every role in the Kids Venue Booking PRD (Section 2.1).

The four roles are VenueManager, Coordinator, FinanceClerk (opaque operator
identities) and Guardian (entity-backed against the Booking aggregate: a guardian's
X-User-ID is stored as guardian_user_id and compared on booking-scoped writes).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Guardian tests that do not
# exercise booking ownership (all GET endpoints, and writes rejected by RBAC
# before any ownership comparison).
TEST_USERS = {
    "venue_manager_headers": build_user_headers("test-venue-manager-1", "VenueManager"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "Coordinator"),
    "finance_clerk_headers": build_user_headers("test-finance-clerk-1", "FinanceClerk"),
    # Guardian: shared constant is a fallback for non-ownership tests only.
    "guardian_headers": build_user_headers("test-guardian-1", "Guardian"),
}


def make_guardian_headers(user_id: str) -> dict:
    """For Guardian (entity_backed:Booking). Pass the guardian_user_id that the
    booking was created with whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Guardian")
