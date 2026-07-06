"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed: Customer and CorporateBuyer. For those, X-User-ID
must be the acting Customer's id whenever the call is ownership-gated; use the
make_*_headers(user_id) builders. The shared TEST_USERS constants are only safe
for opaque operator roles and for non-ownership tests (bad payload / not found /
forbidden-role).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constant is the canonical form.
    "inventory_manager_headers": build_user_headers("test-inv-1", "InventoryManager"),
    "compliance_officer_headers": build_user_headers("test-comp-1", "ComplianceOfficer"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "corporate_buyer_headers": build_user_headers("test-buyer-1", "CorporateBuyer"),
}


# --- Per-instance builders for entity-backed roles (mandatory for ownership-gated calls) ---

def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the acting Customer.id as user_id
    whenever the call is ownership-gated (own subscription/order/redeem)."""
    return build_user_headers(user_id, "Customer")


def make_corporate_buyer_headers(user_id: str) -> dict:
    """For CorporateBuyer (entity_backed:Customer). Pass the acting Customer.id as user_id
    whenever the call is ownership-gated (own bulk quote)."""
    return build_user_headers(user_id, "CorporateBuyer")
