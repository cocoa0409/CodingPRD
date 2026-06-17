"""Pre-built role headers for every role in the PRD.

The Customer role is entity-backed: ownership checks compare the acting
appointment/membership's customer_id against X-User-ID. Any fixture that
performs an ownership-gated Customer call MUST build headers with the actual
Customer.id via make_customer_headers(customer_id); the shared TEST_USERS
constant is only safe for non-ownership tests (e.g. a forbidden-role 403 or a
404 on a missing resource). The other three roles are opaque operator
identities not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise
# Customer ownership.
TEST_USERS = {
    # entity_backed role: this constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles: the shared constant is the canonical form.
    "detailer_headers": build_user_headers("test-detailer-1", "Detailer"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "shop_manager_headers": build_user_headers("test-shop-manager-1", "ShopManager"),
}


# Per-instance builder — required for the entity_backed Customer role.
def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (booking, paying, cancelling,
    activating/cancelling one's own membership, filing rework on one's own
    appointment)."""
    return build_user_headers(customer_id, "Customer")


# Opaque-role builders for symmetry / explicit opaque ids.
def make_detailer_headers(opaque_id: str = "test-detailer-1") -> dict:
    return build_user_headers(opaque_id, "Detailer")


def make_scheduler_headers(opaque_id: str = "test-scheduler-1") -> dict:
    return build_user_headers(opaque_id, "Scheduler")


def make_shop_manager_headers(opaque_id: str = "test-shop-manager-1") -> dict:
    return build_user_headers(opaque_id, "ShopManager")
