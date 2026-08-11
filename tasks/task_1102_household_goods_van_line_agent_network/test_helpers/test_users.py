"""Pre-built role headers for every role in the PRD (section 2.1).

Entity-backed roles (the four agent roles and Customer) get per-instance
builders: any ownership-gated call MUST pass the backing entity's real id.
The shared constants for entity-backed roles are fallbacks for tests that do
not exercise ownership (e.g. 400/404 paths). Opaque roles
(VanLineAdmin / ClaimsAdjuster / Arbitrator) use the shared constants freely.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical form.
    "van_line_admin_headers": build_user_headers("vl-admin-1", "VanLineAdmin"),
    "claims_adjuster_headers": build_user_headers("adj-1", "ClaimsAdjuster"),
    "arbitrator_headers": build_user_headers("arb-1", "Arbitrator"),
    # Entity-backed fallbacks — never ownership-correct; do not use on
    # ownership-gated calls (use the make_*_headers builders below).
    "booking_agent_headers": build_user_headers("test-booking-agent-1", "BookingAgent"),
    "origin_agent_headers": build_user_headers("test-origin-agent-1", "OriginAgent"),
    "hauling_agent_headers": build_user_headers("test-hauling-agent-1", "HaulingAgent"),
    "destination_agent_headers": build_user_headers(
        "test-destination-agent-1", "DestinationAgent"
    ),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


# Per-instance builders — required for entity_backed roles on ownership-gated
# calls: pass the actual Agent.id / Customer.id.
def make_booking_agent_headers(agent_id: str) -> dict:
    """BookingAgent is entity-backed by Agent; pass the agent's real id."""
    return build_user_headers(agent_id, "BookingAgent")


def make_origin_agent_headers(agent_id: str) -> dict:
    """OriginAgent is entity-backed by Agent; pass the agent's real id."""
    return build_user_headers(agent_id, "OriginAgent")


def make_hauling_agent_headers(agent_id: str) -> dict:
    """HaulingAgent is entity-backed by Agent; pass the agent's real id."""
    return build_user_headers(agent_id, "HaulingAgent")


def make_destination_agent_headers(agent_id: str) -> dict:
    """DestinationAgent is entity-backed by Agent; pass the agent's real id."""
    return build_user_headers(agent_id, "DestinationAgent")


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity-backed by Customer; pass the customer's real id."""
    return build_user_headers(customer_id, "Customer")


def make_van_line_admin_headers(user_id: str = "vl-admin-1") -> dict:
    """VanLineAdmin is opaque; user_id is an operator identifier."""
    return build_user_headers(user_id, "VanLineAdmin")


def make_claims_adjuster_headers(user_id: str = "adj-1") -> dict:
    """ClaimsAdjuster is opaque; user_id is an operator identifier."""
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_arbitrator_headers(user_id: str = "arb-1") -> dict:
    """Arbitrator is opaque; user_id is an operator identifier."""
    return build_user_headers(user_id, "Arbitrator")
