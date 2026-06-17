"""Pre-built role headers for every role in the PRD (§2.1).

Three roles:
  * FleetManager — identity is opaque (X-User-ID not tied to any entity).
  * LocationAgent — identity is opaque.
  * Customer — identity is entity_backed:Customer; X-User-ID must equal the
    acting Customer entity's id for ownership-gated calls. Use
    make_customer_headers(customer_id) whenever the call is ownership-gated
    (create/confirm/cancel a reservation, read own reservation/contract).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the two opaque operator roles, and for Customer
# only on tests that do NOT exercise ownership (e.g. 401/403/422 on bad input).
TEST_USERS = {
    "fleet_manager_headers": build_user_headers("test-fleet-manager-1", "FleetManager"),
    "location_agent_headers": build_user_headers("test-location-agent-1", "LocationAgent"),
    # Customer shared constant: a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the real Customer.id as
    user_id on every ownership-gated call so X-User-ID == reservation.customer_id."""
    return build_user_headers(user_id, "Customer")
