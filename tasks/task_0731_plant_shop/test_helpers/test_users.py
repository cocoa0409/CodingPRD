"""Pre-built role headers for every role in the PRD.

Two roles are entity_backed (Customer, DeliveryDriver): use make_*_headers(id)
to pass the actual entity id for ownership-gated calls.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Anonymous: opaque token; server must not compare X-User-ID to any entity id.
    "anonymous_headers": build_user_headers("anon-user", "Anonymous"),
    # opaque operator roles — shared constants are canonical.
    "shop_staff_headers": build_user_headers("test-shop-staff-1", "ShopStaff"),
    "horticulturist_headers": build_user_headers("test-hort-1", "Horticulturist"),
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    # entity_backed roles — these shared constants are fallbacks for NON-ownership-gated
    # tests only (e.g. 400-on-bad-payload). For ownership-gated calls use the make_*
    # builders with the actual entity id.
    "customer_headers": build_user_headers("test-customer-fallback", "Customer"),
    "delivery_driver_headers": build_user_headers("test-driver-fallback", "DeliveryDriver"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id whenever the
    call is ownership-gated (own orders, subscriptions, warranty claims, workshop
    registrations, care reminders, special orders)."""
    return build_user_headers(customer_id, "Customer")


def make_delivery_driver_headers(driver_id: str) -> dict:
    """For DeliveryDriver (entity_backed:DeliveryDriver). Pass the actual DeliveryDriver.id
    when calling ownership-gated endpoints (own deliveries)."""
    return build_user_headers(driver_id, "DeliveryDriver")
