"""Pre-built role headers for every role in the PRD (§2.1).

Two identity models (PRD §2.1):
  - ProgramAdmin, StoreAssociate, FraudAnalyst are opaque operators; X-User-ID is not
    tied to any entity, so the shared TEST_USERS constants are the canonical form.
  - Customer and B2BBuyer are entity-backed: X-User-ID must be the acting Customer's id.
    Ownership-gated calls MUST use the per-instance builders make_customer_headers /
    make_b2b_buyer_headers with the real Customer.id, never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque-operator roles use these as their canonical form.
# The Customer/B2BBuyer entries are fallbacks for tests that do NOT exercise ownership.
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "store_associate_headers": build_user_headers("test-store-1", "StoreAssociate"),
    "fraud_analyst_headers": build_user_headers("test-fraud-1", "FraudAnalyst"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "b2b_buyer_headers": build_user_headers("test-buyer-1", "B2BBuyer"),
}


# Per-instance builders — required for the entity-backed roles.
def make_customer_headers(user_id: str) -> dict:
    """For a Customer (entity_backed:Customer). Pass the acting Customer.id as user_id
    whenever the call is ownership-gated (own card / redemption / refund / replacement)."""
    return build_user_headers(user_id, "Customer")


def make_b2b_buyer_headers(user_id: str) -> dict:
    """For a B2BBuyer (entity_backed:Customer). Pass the corporate Customer.id as user_id
    whenever the call is ownership-gated (own bulk order)."""
    return build_user_headers(user_id, "B2BBuyer")
