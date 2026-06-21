"""Pre-built role headers for every role in the PRD (§2.1).

The Buyer and Seller roles are entity-backed: their X-User-ID must equal a real
Account.id for ownership checks to pass. Tests that exercise ownership MUST use the
per-instance builders (make_buyer_headers / make_seller_headers) with the actual
Account id. The shared constants are only safe for opaque roles (Anonymous,
PlatformAdmin) and for tests whose success does not depend on resource ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# - Anonymous / PlatformAdmin are opaque: shared constants are the canonical form.
# - Buyer / Seller shared constants are fallbacks for NON-ownership tests only
#   (e.g. a forbidden-role check that fails before ownership is evaluated).
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-public-1", "Anonymous"),
    "admin_headers": build_user_headers("admin-operator-1", "PlatformAdmin"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
    "seller_headers": build_user_headers("test-seller-1", "Seller"),
}


# Per-instance builders — mandatory for the entity-backed Buyer and Seller roles.
def make_buyer_headers(account_id: str) -> dict:
    """Headers for a Buyer acting as Account `account_id`. Pass the real Account.id
    whenever the call is ownership-gated (bids, offers, orders, disputes)."""
    return build_user_headers(account_id, "Buyer")


def make_seller_headers(account_id: str) -> dict:
    """Headers for a Seller acting as Account `account_id`. Pass the real Account.id
    whenever the call is ownership-gated (listings, orders, invoices)."""
    return build_user_headers(account_id, "Seller")


def make_anonymous_headers(user_id: str = "anon-public-1") -> dict:
    return build_user_headers(user_id, "Anonymous")


def make_admin_headers(user_id: str = "admin-operator-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
