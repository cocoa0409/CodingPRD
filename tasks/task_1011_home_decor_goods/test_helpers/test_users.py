"""Pre-built role headers for every role in the PRD.

Four roles (Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator)
carry an opaque identity — the X-User-ID is an operator id not tied to any
persisted entity, so shared constants are always correct for them.

The Customer role is entity-backed by a LoyaltyMember: its X-User-ID must be
the acting member's id whenever an ownership check applies (registry ops). Use
make_customer_headers(member_id) for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — correct for the four opaque roles, and a non-ownership
# fallback for Customer (e.g. role-denied tests that never reach an owner check).
TEST_USERS = {
    "admin_headers": build_user_headers("op-admin-1", "Admin"),
    "merch_headers": build_user_headers("op-merch-1", "MerchandisingManager"),
    "associate_headers": build_user_headers("op-associate-1", "StoreAssociate"),
    "delivery_headers": build_user_headers("op-delivery-1", "DeliveryCoordinator"),
    "customer_headers": build_user_headers("member-fallback-1", "Customer"),
}


def make_customer_headers(member_id: str) -> dict:
    """For Customer (entity_backed:LoyaltyMember). Pass the acting member's id as
    X-User-ID whenever the call is ownership-gated (registry create/items/close)."""
    return build_user_headers(member_id, "Customer")
