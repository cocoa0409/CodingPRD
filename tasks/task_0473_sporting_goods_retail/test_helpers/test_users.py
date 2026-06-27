"""Pre-built role headers for every role in the PRD.

Per PRD §2.1, four of the five roles (PlatformAdmin, StoreAssociate, ServiceTech,
PriceAdmin) carry an *opaque* X-User-ID that the server records but never compares
to any entity id; for those, the shared constant is the canonical form.

The Customer role is *entity-backed*: X-User-ID is the id of the acting Customer,
and ownership-gated calls (placing/cancelling an order, submitting a price-match
claim on its own order, submitting an owned team order) compare the resource's
customer_id to X-User-ID. For those calls the per-instance builder
make_customer_headers(customer_id) MUST be used with the real Customer.id, never
the shared TEST_USERS["customer_headers"] constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles; for Customer the shared constant
# is a fallback used only by tests that do not exercise ownership (e.g. 401/403
# negative checks where no real customer id is required).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("op-platform-admin-1", "PlatformAdmin"),
    "store_associate_headers": build_user_headers("op-store-associate-1", "StoreAssociate"),
    "service_tech_headers": build_user_headers("op-service-tech-1", "ServiceTech"),
    "price_admin_headers": build_user_headers("op-price-admin-1", "PriceAdmin"),
    "customer_headers": build_user_headers("op-customer-fallback-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For the Customer role (entity_backed:Customer).

    Pass the actual Customer.id as the X-User-ID so ownership checks resolve.
    """
    return build_user_headers(customer_id, "Customer")
