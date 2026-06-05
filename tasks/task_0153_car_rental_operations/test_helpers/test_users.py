"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# FleetManager and RentalAgent carry opaque operator identifiers not tied to any
# persisted entity (PRD §2.1), so a shared constant is the canonical form for them.
# The Member shared constant is a fallback for non-ownership tests only — any
# ownership-gated Member call MUST use make_member_headers(member_id) instead.
TEST_USERS = {
    "fleet_manager_headers": build_user_headers("test-fleet-manager-1", "FleetManager"),
    "rental_agent_headers": build_user_headers("test-rental-agent-1", "RentalAgent"),
    "member_headers": build_user_headers("test-member-fallback-1", "Member"),
}


def make_fleet_manager_headers(user_id: str = "test-fleet-manager-1") -> dict:
    """FleetManager is opaque; X-User-ID is an operator identifier."""
    return build_user_headers(user_id, "FleetManager")


def make_rental_agent_headers(user_id: str = "test-rental-agent-1") -> dict:
    """RentalAgent is opaque; X-User-ID is an operator identifier."""
    return build_user_headers(user_id, "RentalAgent")


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:LoyaltyMember). Pass the actual LoyaltyMember.id
    as user_id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "Member")
