"""Pre-built role headers for every role in the PRD (§2.1).

Dealer is an entity-backed role: when a call is ownership-gated (order
submit/cancel, line creation, mod creation/resubmit, claim filing), the
headers MUST be built with the actual Dealer record's id via
make_dealer_headers(). The shared constant exists only for tests whose
success does not depend on owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are canonical.
    "plant_admin_headers": build_user_headers("test-plant-admin-1", "PlantAdmin"),
    "engineer_headers": build_user_headers("test-engineer-1", "Engineer"),
    "finish_supervisor_headers": build_user_headers("test-finish-supervisor-1", "FinishSupervisor"),
    "production_planner_headers": build_user_headers("test-production-planner-1", "ProductionPlanner"),
    "shipping_coordinator_headers": build_user_headers("test-shipping-coordinator-1", "ShippingCoordinator"),
    # Entity-backed role: fallback only for non-ownership tests (the id below
    # will never equal a persisted Dealer.id, so ownership-gated calls fail).
    "dealer_headers": build_user_headers("test-dealer-unbound", "Dealer"),
}


def make_dealer_headers(dealer_id: str) -> dict:
    """Headers for the entity-backed Dealer role. Pass the actual Dealer.id
    whenever the call is ownership-gated."""
    return build_user_headers(dealer_id, "Dealer")


def make_plant_admin_headers(user_id: str = "test-plant-admin-1") -> dict:
    return build_user_headers(user_id, "PlantAdmin")


def make_engineer_headers(user_id: str = "test-engineer-1") -> dict:
    return build_user_headers(user_id, "Engineer")


def make_finish_supervisor_headers(user_id: str = "test-finish-supervisor-1") -> dict:
    return build_user_headers(user_id, "FinishSupervisor")


def make_production_planner_headers(user_id: str = "test-production-planner-1") -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_shipping_coordinator_headers(user_id: str = "test-shipping-coordinator-1") -> dict:
    return build_user_headers(user_id, "ShippingCoordinator")
