"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. For Customer (entity_backed), use make_customer_headers with the
# actual Customer.id whenever the call is ownership-gated.
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles: shared constants are the canonical form.
    "analyst_headers": build_user_headers("analyst-1", "MarginAnalyst"),
    "analyst2_headers": build_user_headers("analyst-2", "MarginAnalyst"),
    "supervisor_headers": build_user_headers("sup-1", "MarginSupervisor"),
    "supervisor2_headers": build_user_headers("sup-2", "MarginSupervisor"),
    "desk1_headers": build_user_headers("desk-1", "LiquidationDesk"),
    "desk2_headers": build_user_headers("desk-2", "LiquidationDesk"),
    "market_ops_headers": build_user_headers("mkt-ops-1", "MarketDataOps"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_analyst_headers(user_id: str) -> dict:
    """For MarginAnalyst (opaque)."""
    return build_user_headers(user_id, "MarginAnalyst")


def make_supervisor_headers(user_id: str) -> dict:
    """For MarginSupervisor (opaque)."""
    return build_user_headers(user_id, "MarginSupervisor")


def make_desk_headers(user_id: str) -> dict:
    """For LiquidationDesk (opaque)."""
    return build_user_headers(user_id, "LiquidationDesk")


def make_market_ops_headers(user_id: str) -> dict:
    """For MarketDataOps (opaque)."""
    return build_user_headers(user_id, "MarketDataOps")
