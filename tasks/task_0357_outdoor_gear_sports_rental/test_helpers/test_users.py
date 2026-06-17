"""Pre-built role headers for every role in the PRD.

ShopAdmin and RentalAgent are opaque operator identities — the shared constant
is the canonical form. Renter is entity_backed:Customer — ownership-gated calls
MUST use make_renter_headers(customer_id) with the real Customer.id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - ShopAdmin / RentalAgent: opaque identity, shared constant is canonical.
#   - Renter: shared constant is a fallback for non-ownership tests only.
TEST_USERS = {
    "shop_admin_headers": build_user_headers("admin-1", "ShopAdmin"),
    "rental_agent_headers": build_user_headers("agent-1", "RentalAgent"),
    "renter_headers": build_user_headers("renter-1", "Renter"),
}


def make_renter_headers(user_id: str) -> dict:
    """For Renter (entity_backed:Customer). Pass the acting Customer.id as user_id
    whenever the call is ownership-gated (confirm/cancel/addons/dispute on own
    reservation)."""
    return build_user_headers(user_id, "Renter")


def make_shop_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "ShopAdmin")


def make_rental_agent_headers(user_id: str = "agent-1") -> dict:
    return build_user_headers(user_id, "RentalAgent")
