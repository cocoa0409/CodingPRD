"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed per PRD §2.1: DesignEngineer (backed by Engineer)
and CustomerContact (backed by CustomerAccount). For those, ownership/attribution
checks compare X-User-ID against a real entity id, so callers MUST use the
per-instance builders with the actual entity id. The shared TEST_USERS entries
for those two roles are fallbacks for tests that never exercise ownership or
attribution (e.g. 400/404 paths).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "design_engineer_headers": build_user_headers("test-eng-fallback", "DesignEngineer"),
    "customer_contact_headers": build_user_headers("test-cust-fallback", "CustomerContact"),
    # opaque roles: shared constants are the canonical form.
    "plant_manager_headers": build_user_headers("test-pm-1", "PlantManager"),
    "production_planner_headers": build_user_headers("test-pp-1", "ProductionPlanner"),
    "inventory_manager_headers": build_user_headers("test-im-1", "InventoryManager"),
    "shop_floor_lead_headers": build_user_headers("test-sfl-1", "ShopFloorLead"),
    "shipping_coordinator_headers": build_user_headers("test-sc-1", "ShippingCoordinator"),
    "claims_adjuster_headers": build_user_headers("adj-1", "ClaimsAdjuster"),
}


def make_design_engineer_headers(engineer_id: str) -> dict:
    """For DesignEngineer (entity-backed by Engineer). Pass the acting Engineer's id."""
    return build_user_headers(engineer_id, "DesignEngineer")


def make_customer_contact_headers(customer_id: str) -> dict:
    """For CustomerContact (entity-backed by CustomerAccount). Pass the account's id."""
    return build_user_headers(customer_id, "CustomerContact")


def make_claims_adjuster_headers(user_id: str) -> dict:
    """ClaimsAdjuster is opaque, but triaged_by/decided_by record X-User-ID and the
    decider must differ from the triager, so pass a distinct id per adjuster."""
    return build_user_headers(user_id, "ClaimsAdjuster")
