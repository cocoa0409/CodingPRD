"""Pre-built role headers for every role in the PRD.

PRD §2.1: StoreManager, StoreClerk, DeliveryDriver identities are opaque
operator identifiers — the shared constant is the canonical form. Customer
identity is entity_backed: ownership checks compare the resource's
customer FK to X-User-ID, so tests exercising Customer-owned mutations
MUST use make_customer_headers(actual_customer_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles; fallback-only for entity_backed
# roles (fine for non-ownership tests such as 400/404 fast-fail paths).
TEST_USERS = {
    "store_manager_headers": build_user_headers("test-store-manager-1", "StoreManager"),
    "store_clerk_headers": build_user_headers("test-store-clerk-1", "StoreClerk"),
    "delivery_driver_headers": build_user_headers("test-delivery-driver-1", "DeliveryDriver"),
    "customer_headers": build_user_headers("test-customer-fallback-1", "Customer"),
}


def make_store_manager_headers(user_id: str = "test-store-manager-1") -> dict:
    return build_user_headers(user_id, "StoreManager")


def make_store_clerk_headers(user_id: str = "test-store-clerk-1") -> dict:
    return build_user_headers(user_id, "StoreClerk")


def make_delivery_driver_headers(user_id: str = "test-delivery-driver-1") -> dict:
    return build_user_headers(user_id, "DeliveryDriver")


def make_customer_headers(customer_id: str) -> dict:
    """For Customer role (identity=entity_backed:Customer).

    Pass the real Customer.id as customer_id whenever the call is
    ownership-gated (request-revision, approve on the customer's own
    CustomPrintOrder). PRD §2.1 requires X-User-ID to equal the
    Customer.id for ownership to resolve.
    """
    return build_user_headers(customer_id, "Customer")
