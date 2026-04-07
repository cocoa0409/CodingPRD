"""
E-Commerce Marketplace — pre-built test user headers (scaffold Table 7 RBAC).

Each variable is a dict ready to pass as ``headers=`` to httpx / requests.
"""

from prd_bench_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# User IDs  (stable UUIDs for deterministic tests)
# ---------------------------------------------------------------------------

CUSTOMER_USER_ID = "c0000000-0000-0000-0000-000000000001"
SELLER_USER_ID = "s0000000-0000-0000-0000-000000000001"
ADMIN_USER_ID = "a0000000-0000-0000-0000-000000000001"

# Second seller for cross-shop / ownership tests
SELLER_2_USER_ID = "s0000000-0000-0000-0000-000000000002"

# Second customer for ownership tests
CUSTOMER_2_USER_ID = "c0000000-0000-0000-0000-000000000002"

# ---------------------------------------------------------------------------
# Pre-built header dicts
# ---------------------------------------------------------------------------

CUSTOMER_HEADERS = build_user_headers(CUSTOMER_USER_ID, "Customer")
SELLER_HEADERS = build_user_headers(SELLER_USER_ID, "Seller")
ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, "PlatformAdmin")

SELLER_2_HEADERS = build_user_headers(SELLER_2_USER_ID, "Seller")
CUSTOMER_2_HEADERS = build_user_headers(CUSTOMER_2_USER_ID, "Customer")

# ---------------------------------------------------------------------------
# Aggregate dict (used by fixtures and helpers)
# ---------------------------------------------------------------------------

TEST_USERS = {
    "customer_headers": CUSTOMER_HEADERS,
    "seller_headers": SELLER_HEADERS,
    "admin_headers": ADMIN_HEADERS,
    "seller2_headers": SELLER_2_HEADERS,
    "customer2_headers": CUSTOMER_2_HEADERS,
}
