"""Pre-built role headers for every role in the PRD (§2.1).

Dispatcher, Customer, InventoryManager, BillingAgent carry an OPAQUE X-User-ID
not tied to any persisted entity. Technician is entity_backed: its X-User-ID must
equal the acting technician's id whenever an operation runs as that technician.
The Customer X-User-ID is the opaque value recorded as customer_user_id at intake;
ownership-gated quote/warranty actions compare it to the job's customer_user_id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# Technician identity or Customer ownership (e.g. 401/403/404 checks, reads, intake).
TEST_USERS = {
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "inventory_manager_headers": build_user_headers("inventory-1", "InventoryManager"),
    "billing_agent_headers": build_user_headers("billing-1", "BillingAgent"),
    "customer_headers": build_user_headers("customer-1", "Customer"),
    # Technician shared constant: fallback for NON-identity tests only
    # (its X-User-ID equals no real technician id).
    "technician_headers": build_user_headers("technician-shared", "Technician"),
}


def make_technician_headers(technician_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual Technician.id as
    user_id whenever the call runs as that technician."""
    return build_user_headers(technician_id, "Technician")


def make_customer_headers(customer_user_id: str) -> dict:
    """For Customer (opaque, but ownership-checked). Pass the value recorded as the
    job's customer_user_id whenever the call is ownership-gated (approve / reject /
    request-revision / file warranty claim)."""
    return build_user_headers(customer_user_id, "Customer")
