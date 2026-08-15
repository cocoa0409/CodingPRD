"""Pre-built role headers for every role in the PRD (§2.1).

Only Mechanic is entity-backed: X-User-ID must be the acting Mechanic record's
id whenever the call is ownership-gated (labor entries, QA events, road-call
arrive/clear, shift self-confirm). Use make_mechanic_headers(mechanic["id"])
for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "fleet_manager_headers": build_user_headers("test-fleet-manager-1", "FleetManager"),
    "supervisor_headers": build_user_headers(
        "test-supervisor-1", "MaintenanceSupervisor"
    ),
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "mechanic_headers": build_user_headers("test-mechanic-1", "Mechanic"),
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    "parts_clerk_headers": build_user_headers("test-parts-clerk-1", "PartsClerk"),
    "warranty_clerk_headers": build_user_headers("test-warranty-clerk-1", "WarrantyClerk"),
}


def make_mechanic_headers(user_id: str) -> dict:
    """For Mechanic (entity_backed: Mechanic). Pass the actual Mechanic.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Mechanic")


def make_fleet_manager_headers(user_id: str) -> dict:
    """FleetManager is opaque; a distinct user id is needed for recovery SoD
    tests (caller X-User-ID vs claim submitted_by_user_id)."""
    return build_user_headers(user_id, "FleetManager")


def make_warranty_clerk_headers(user_id: str) -> dict:
    """WarrantyClerk is opaque; submit with a stable user id so the recovery
    SoD check compares against a known submitted_by_user_id."""
    return build_user_headers(user_id, "WarrantyClerk")
