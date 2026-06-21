"""Pre-built role headers for every role in the PRD (§2.1).

Three roles (FrontDesk, LeagueAdmin, CenterManager) carry an opaque operator
identity, so their shared constants are the canonical form. The Customer role is
entity-backed: X-User-ID must equal the acting Customer's id for ownership checks
to pass, so ownership-gated Customer calls MUST use make_customer_headers(id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
    "league_admin_headers": build_user_headers("test-leagueadmin-1", "LeagueAdmin"),
    "center_manager_headers": build_user_headers("test-centermanager-1", "CenterManager"),
    # Customer (entity_backed): shared constant is a fallback ONLY for tests that
    # do not exercise ownership (e.g. a 403-forbidden RBAC check on a create that
    # never reaches an ownership comparison).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated (reservation/food/rental
    mutations on a reservation the customer owns)."""
    return build_user_headers(user_id, "Customer")
