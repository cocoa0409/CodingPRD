"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# resource ownership (missing-resource, bad-payload, or authorization-only cases).
TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "dispatch_planner_headers": build_user_headers("test-planner-1", "DispatchPlanner"),
    "dock_coordinator_headers": build_user_headers("test-dock-1", "DockCoordinator"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "delivery_lead_headers": build_user_headers("test-lead-1", "DeliveryLead"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}

# Requests carrying no authentication headers (§2.1 — ERR_UNAUTHENTICATED).
NO_AUTH_HEADERS: dict = {}


# --- Per-instance builders (required for every entity_backed role) ---

def make_delivery_lead_headers(team_id: str) -> dict:
    """For DeliveryLead (entity_backed:DeliveryTeam). Pass the acting crew's
    DeliveryTeam.id as X-User-ID whenever the call is ownership-gated (§2.1:
    X-User-ID is the id of the acting DeliveryTeam)."""
    return build_user_headers(team_id, "DeliveryLead")


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the acting Customer.id as
    X-User-ID whenever the call is ownership-gated (§2.1: X-User-ID is the id
    of the acting Customer)."""
    return build_user_headers(customer_id, "Customer")
