"""Pre-built role headers for every role in the PRD (§2.1).

Five roles: SalesRep (opaque), Dispatcher (opaque), BillingAdmin (opaque),
Customer (entity_backed:Customer), CrewLead (entity_backed:Crew).

Ownership-gated calls for the two entity-backed roles MUST use the per-instance
builders below with the actual entity id, never the shared constants — the shared
X-User-ID is a string that never equals any real entity's id, so every ownership
check would reject it (PRD §2.1: Customer accept/payment ownership, CrewLead
start/complete ownership).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "salesrep_headers": build_user_headers("test-salesrep-1", "SalesRep"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "billingadmin_headers": build_user_headers("test-billing-1", "BillingAdmin"),
    # Entity-backed roles: shared constants are fallbacks for non-ownership tests
    # only (401/403/404/422 negatives that never pass the ownership gate).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "crewlead_headers": build_user_headers("test-crew-1", "CrewLead"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (accept estimate, post payment on own plan)."""
    return build_user_headers(user_id, "Customer")


def make_crewlead_headers(user_id: str) -> dict:
    """For CrewLead (entity_backed:Crew). Pass the actual Crew.id as user_id whenever
    the call is ownership-gated (start/complete a job on that crew's route day)."""
    return build_user_headers(user_id, "CrewLead")
