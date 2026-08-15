"""Pre-built role headers for every role in the PRD.

Six roles are opaque operator identities (PRD section 2.1): the server does not
compare their X-User-ID to any entity id, so the shared constants are canonical.

DealerUser is entity-backed: X-User-ID must be the id of an existing Dealer.
The shared constant exists only for tests that never pass an ownership check
(e.g. a role rejection); every ownership-gated call MUST be built with
make_dealer_user_headers(dealer_id).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "supply_admin_headers": build_user_headers("supply-admin-1", "SupplyAdmin"),
    "supply_planner_headers": build_user_headers("supply-planner-1", "SupplyPlanner"),
    "pricing_desk_headers": build_user_headers("pricing-desk-1", "PricingDesk"),
    "credit_manager_headers": build_user_headers("credit-manager-1", "CreditManager"),
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "system_admin_headers": build_user_headers("system-admin-1", "SystemAdmin"),
    # Fallback only — entity-backed role; use make_dealer_user_headers(dealer_id)
    # for any call whose ownership check compares dealer_id to X-User-ID.
    "dealer_user_headers": build_user_headers("dealer-user-unbound", "DealerUser"),
}


def make_dealer_user_headers(user_id: str) -> dict:
    """DealerUser is entity-backed: pass the actual Dealer.id as user_id
    whenever the call is ownership-gated (order create/cancel, own reads)."""
    return build_user_headers(user_id, "DealerUser")


def make_supply_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SupplyAdmin")


def make_supply_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SupplyPlanner")


def make_pricing_desk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PricingDesk")


def make_credit_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CreditManager")


def make_dispatcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")
