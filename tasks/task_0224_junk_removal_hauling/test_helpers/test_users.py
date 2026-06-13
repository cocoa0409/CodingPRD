"""Pre-built role headers for every role in the PRD (Junk Removal & Hauling)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - PlatformAdmin, Dispatcher, and Billing are opaque operator identities: the
#    shared constant is the canonical form (X-User-ID is never matched to an entity id).
#  - Customer (entity_backed:Customer) and CrewLead (entity_backed:Crew) shared
#    constants are fallbacks for tests that do NOT exercise ownership (e.g. 401/403/404
#    negative tests). Ownership-gated calls MUST use the per-instance builders below
#    with the real entity id.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "billing_headers": build_user_headers("test-billing-1", "Billing"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "crew_lead_headers": build_user_headers("test-crewlead-1", "CrewLead"),
}


# Per-instance builders — required for every entity_backed role.

def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the acting Customer.id as X-User-ID
    whenever the call is ownership-gated (create/estimate/accept/revise/cancel/dispute
    against jobs and invoices the customer owns)."""
    return build_user_headers(customer_id, "Customer")


def make_crew_lead_headers(crew_id: str) -> dict:
    """For CrewLead (entity_backed:Crew). Pass the acting Crew.id as X-User-ID whenever
    the call is ownership-gated (arrive/load/divert/dump on the job assigned to that crew)."""
    return build_user_headers(crew_id, "CrewLead")
