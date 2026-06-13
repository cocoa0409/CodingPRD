"""Pre-built role headers for every role in the PRD (§2.1).

Five roles — StoreManager, ReceivingClerk, PriceManager, Cashier,
InventoryAuditor — are opaque: X-User-ID is an arbitrary operator handle never
compared to any entity id, so the shared constant form is canonical for them.

LoyaltyMember is entity_backed: X-User-ID must equal the acting member's id.
Ownership-gated LoyaltyMember calls MUST use make_member_headers(member_id).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "store_manager_headers": build_user_headers("mgr-1", "StoreManager"),
    "receiving_clerk_headers": build_user_headers("rc-1", "ReceivingClerk"),
    "price_manager_headers": build_user_headers("pm-1", "PriceManager"),
    "cashier_headers": build_user_headers("csh-1", "Cashier"),
    "inventory_auditor_headers": build_user_headers("aud-1", "InventoryAuditor"),
    # Opaque fallback for LoyaltyMember in non-ownership tests only.
    "loyalty_member_headers": build_user_headers("member-shared", "LoyaltyMember"),
}


def make_store_manager_headers(user_id: str = "mgr-1") -> dict:
    return build_user_headers(user_id, "StoreManager")


def make_receiving_clerk_headers(user_id: str = "rc-1") -> dict:
    return build_user_headers(user_id, "ReceivingClerk")


def make_price_manager_headers(user_id: str = "pm-1") -> dict:
    return build_user_headers(user_id, "PriceManager")


def make_cashier_headers(user_id: str = "csh-1") -> dict:
    return build_user_headers(user_id, "Cashier")


def make_inventory_auditor_headers(user_id: str = "aud-1") -> dict:
    return build_user_headers(user_id, "InventoryAuditor")


def make_member_headers(member_id: str) -> dict:
    """For LoyaltyMember (entity_backed:LoyaltyMember). Pass the actual
    LoyaltyMember.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(member_id, "LoyaltyMember")
