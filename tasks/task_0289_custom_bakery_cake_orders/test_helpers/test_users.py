"""Pre-built role headers for every role in the PRD.

The Customer role is entity_backed: a customer-owned action under an order
compares the order's customer_id to X-User-ID, so ownership-gated calls MUST use
make_customer_headers(<the actual Customer.id>). The shared TEST_USERS constant
for Customer is a fallback only for tests that do not exercise ownership.

BakeryStaff, DeliveryDispatcher, BakeryManager, and Anonymous are opaque roles:
their X-User-ID is an operator identifier never compared to an entity id, so the
shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles: shared constants are the canonical form.
    "staff_headers": build_user_headers("test-staff-1", "BakeryStaff"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "DeliveryDispatcher"),
    "manager_headers": build_user_headers("test-manager-1", "BakeryManager"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (any /orders/{id}/* customer
    action where the order's customer_id must equal X-User-ID)."""
    return build_user_headers(user_id, "Customer")


def make_staff_headers(user_id: str = "test-staff-1") -> dict:
    """For BakeryStaff (opaque)."""
    return build_user_headers(user_id, "BakeryStaff")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    """For DeliveryDispatcher (opaque)."""
    return build_user_headers(user_id, "DeliveryDispatcher")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    """For BakeryManager (opaque)."""
    return build_user_headers(user_id, "BakeryManager")
