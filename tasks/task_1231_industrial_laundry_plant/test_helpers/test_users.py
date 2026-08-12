"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlantAdmin, RouteDriver,
# PlantOperator, CustomerServiceRep, BillingClerk): for these roles X-User-ID
# is not compared to any entity id (PRD §2.1). The CustomerContact entry is a
# fallback for tests that do not exercise ownership; ownership-gated calls
# MUST use make_customer_contact_headers(<customer id>).
TEST_USERS = {
    "plant_admin_headers": build_user_headers("test-plant-admin-1", "PlantAdmin"),
    "route_driver_headers": build_user_headers("test-route-driver-1", "RouteDriver"),
    "plant_operator_headers": build_user_headers("test-plant-operator-1", "PlantOperator"),
    "csr_headers": build_user_headers("test-csr-1", "CustomerServiceRep"),
    "billing_clerk_headers": build_user_headers("test-billing-clerk-1", "BillingClerk"),
    # entity_backed: fallback only for non-ownership checks.
    "customer_contact_headers": build_user_headers("test-customer-contact-1", "CustomerContact"),
}


def make_customer_contact_headers(customer_id: str) -> dict:
    """For CustomerContact (entity_backed:Customer). Pass the actual
    Customer.id whenever the call is ownership-gated (PRD §2.1: X-User-ID is
    the id of the acting Customer)."""
    return build_user_headers(customer_id, "CustomerContact")
