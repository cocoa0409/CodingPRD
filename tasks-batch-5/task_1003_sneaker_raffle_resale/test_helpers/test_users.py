"""Pre-built role headers for every role in the PRD.

Buyer and Seller are backed by an Account; Authenticator is backed by an
Authenticator entity — ownership checks compare X-User-ID to the relevant
entity id, so ownership-gated calls MUST use the per-instance builders below
with the real entity id. PlatformAdmin and CustomerService are opaque
operator identifiers not tied to any persisted entity, so their shared
constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque operator roles, and for tests that do
# not exercise ownership (e.g. 404 on a missing resource, 422 on a bad body).
TEST_USERS = {
    "admin_headers": build_user_headers("operator-admin-1", "PlatformAdmin"),
    "cs_headers": build_user_headers("operator-cs-1", "CustomerService"),
    # entity_backed fallbacks — only for non-ownership tests.
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
    "seller_headers": build_user_headers("test-seller-1", "Seller"),
    "authenticator_headers": build_user_headers("test-auth-1", "Authenticator"),
}


# Per-instance builders — required for every entity_backed role.
def make_buyer_headers(account_id: str) -> dict:
    """For Buyer (backed by Account). Pass the acting Account.id as user_id."""
    return build_user_headers(account_id, "Buyer")


def make_seller_headers(account_id: str) -> dict:
    """For Seller (backed by Account). Pass the acting Account.id as user_id."""
    return build_user_headers(account_id, "Seller")


def make_authenticator_headers(authenticator_id: str) -> dict:
    """For Authenticator (backed by Authenticator). Pass the acting Authenticator.id."""
    return build_user_headers(authenticator_id, "Authenticator")
