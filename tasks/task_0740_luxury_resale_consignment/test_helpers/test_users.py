"""Pre-built role headers for every role in the PRD (§2.1).

The system recognises exactly five roles: OpsAdmin, Seller, Buyer, Authenticator,
and ConciergeAgent.

- `Seller` and `Buyer` are **entity-backed** (PRD §2.1): X-User-ID is the id of the
  acting Seller / Buyer record, and ownership checks compare the seller_id / buyer_id
  foreign key on the targeted resource against X-User-ID. Ownership-gated calls MUST
  use make_seller_headers(<real Seller.id>) / make_buyer_headers(<real Buyer.id>) —
  the shared constants below are fallbacks for non-ownership tests only.
- `OpsAdmin`, `Authenticator`, and `ConciergeAgent` are **opaque** operator
  identities: the server never compares their X-User-ID to any entity id, so the
  shared constants are the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque operator roles — shared constant is the canonical form.
    "ops_admin_headers": build_user_headers("test-ops-1", "OpsAdmin"),
    "authenticator_headers": build_user_headers("test-auth-1", "Authenticator"),
    "concierge_agent_headers": build_user_headers("test-concierge-1", "ConciergeAgent"),
    # entity_backed roles — shared constant is a fallback for non-ownership tests only.
    "seller_headers": build_user_headers("test-seller-1", "Seller"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
}


def make_seller_headers(user_id: str) -> dict:
    """For Seller (entity_backed:Seller). Pass the actual Seller.id as user_id whenever
    the call is ownership-gated, so the seller_id == X-User-ID ownership check passes."""
    return build_user_headers(user_id, "Seller")


def make_buyer_headers(user_id: str) -> dict:
    """For Buyer (entity_backed:Buyer). Pass the actual Buyer.id as user_id whenever
    the call is ownership-gated, so the buyer_id == X-User-ID ownership check passes."""
    return build_user_headers(user_id, "Buyer")


def make_ops_admin_headers(user_id: str = "test-ops-1") -> dict:
    return build_user_headers(user_id, "OpsAdmin")


def make_authenticator_headers(user_id: str = "test-auth-1") -> dict:
    return build_user_headers(user_id, "Authenticator")


def make_concierge_agent_headers(user_id: str = "test-concierge-1") -> dict:
    return build_user_headers(user_id, "ConciergeAgent")
