"""Pre-built role headers for every role in the PRD.

`SellerOperator` and `FcOperator` are entity-backed: their `X-User-ID` is the
`id` of the acting `SellerAccount` / `FulfillmentCenter`, so ownership-gated
calls MUST use the per-instance builders below with the real entity id.
`ClaimsAdjudicator` and `MarketplaceAdmin` are opaque identifiers never compared
to any entity's `id`, so their shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles, and for entity-backed roles only
# in tests that never reach an ownership comparison (bad payloads, unknown ids,
# role-authorization rejections).
TEST_USERS = {
    "seller_operator_headers": build_user_headers("test-seller-operator-1", "SellerOperator"),
    "fc_operator_headers": build_user_headers("test-fc-operator-1", "FcOperator"),
    "claims_adjudicator_headers": build_user_headers("adj-1", "ClaimsAdjudicator"),
    "marketplace_admin_headers": build_user_headers("admin-1", "MarketplaceAdmin"),
}


def make_seller_operator_headers(seller_account_id: str) -> dict:
    """Headers for a `SellerOperator`. Pass the acting `SellerAccount.id`."""
    return build_user_headers(seller_account_id, "SellerOperator")


def make_fc_operator_headers(fulfillment_center_id: str) -> dict:
    """Headers for an `FcOperator`. Pass the acting `FulfillmentCenter.id`."""
    return build_user_headers(fulfillment_center_id, "FcOperator")


def make_claims_adjudicator_headers(operator_id: str = "adj-1") -> dict:
    """Headers for a `ClaimsAdjudicator` (opaque operator identifier)."""
    return build_user_headers(operator_id, "ClaimsAdjudicator")


def make_marketplace_admin_headers(operator_id: str = "admin-1") -> dict:
    """Headers for a `MarketplaceAdmin` (opaque operator identifier)."""
    return build_user_headers(operator_id, "MarketplaceAdmin")


ADMIN = TEST_USERS["marketplace_admin_headers"]
ADJUDICATOR = TEST_USERS["claims_adjudicator_headers"]
