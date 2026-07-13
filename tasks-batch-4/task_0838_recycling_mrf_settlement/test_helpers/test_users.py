"""Pre-built role headers for every role in the PRD (§2.1).

The four operational roles are opaque; the Municipality role is entity-backed
(X-User-ID equals a Municipality.id). Because a Municipality can only read, and
every GET endpoint is shared with all roles, tests use the shared operational
constants for setup; make_municipality_headers is provided for completeness.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared operational constants — opaque identity, safe for any operation these
# roles are authorized for.
TEST_USERS = {
    "scale_operator_headers": build_user_headers("test-scale-operator-1", "ScaleOperator"),
    "sort_manager_headers": build_user_headers("test-sort-manager-1", "SortManager"),
    "commodity_trader_headers": build_user_headers("test-commodity-trader-1", "CommodityTrader"),
    "settlement_clerk_headers": build_user_headers("test-settlement-clerk-1", "SettlementClerk"),
    # Fallback opaque form for the Municipality role (non-ownership reads).
    "municipality_headers": build_user_headers("test-municipality-1", "Municipality"),
}


def make_municipality_headers(municipality_id: str) -> dict:
    """For the Municipality role (entity_backed:Municipality). Pass the actual
    Municipality.id as user_id when an ownership-scoped read is exercised."""
    return build_user_headers(municipality_id, "Municipality")
