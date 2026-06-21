"""Pre-built role headers for every role in the Tire Shop & Service PRD.

Customer is entity-backed: X-User-ID must be the acting Customer's id whenever an
ownership check applies. The other three roles are opaque operator identifiers that
the server logs but never compares to any entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# - ServiceAdvisor / Technician / InventoryManager are opaque; the constant form is canonical.
# - The Customer constant is a fallback only for tests that do NOT exercise ownership
#   (e.g. 401/403/404 negatives). Ownership-gated calls MUST use make_customer_headers(id).
TEST_USERS = {
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "service_advisor_headers": build_user_headers("test-advisor-1", "ServiceAdvisor"),
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "inventory_manager_headers": build_user_headers("test-inventory-1", "InventoryManager"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (e.g. request-reschedule on own
    appointment)."""
    return build_user_headers(user_id, "Customer")


def make_service_advisor_headers(user_id: str = "test-advisor-1") -> dict:
    return build_user_headers(user_id, "ServiceAdvisor")


def make_technician_headers(user_id: str = "test-technician-1") -> dict:
    return build_user_headers(user_id, "Technician")


def make_inventory_manager_headers(user_id: str = "test-inventory-1") -> dict:
    return build_user_headers(user_id, "InventoryManager")
