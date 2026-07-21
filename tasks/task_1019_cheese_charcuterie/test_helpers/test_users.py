"""Pre-built role headers for every role in the PRD (§2.1).

ShopManager and CounterStaff carry opaque X-User-ID identifiers not tied to any entity.
WholesaleCustomer's X-User-ID is the Customer.id it acts as, so ownership-gated calls
MUST use make_wholesale_customer_headers(customer_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# ShopManager / CounterStaff are opaque operators — the shared constant is canonical.
# The WholesaleCustomer shared constant is a fallback for non-ownership tests only.
TEST_USERS = {
    "shop_manager_headers": build_user_headers("test-shop-manager-1", "ShopManager"),
    "counter_staff_headers": build_user_headers("test-counter-staff-1", "CounterStaff"),
    "wholesale_customer_headers": build_user_headers("test-wholesale-1", "WholesaleCustomer"),
}


def make_wholesale_customer_headers(customer_id: str) -> dict:
    """For WholesaleCustomer (entity_backed:Customer). Pass the acting Customer.id as
    X-User-ID whenever the call is ownership-gated (order/subscription create/act)."""
    return build_user_headers(customer_id, "WholesaleCustomer")


def make_anonymous_headers() -> dict:
    """A request carrying an unknown role — used to exercise ERR_UNAUTHENTICATED."""
    return build_user_headers("anon-1", "Anonymous")
