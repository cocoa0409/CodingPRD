"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# entity-backed ownership (e.g. 400-on-bad-payload, 404-on-missing-resource,
# authorization/authentication checks).
TEST_USERS = {
    "resident_headers": build_user_headers("test-resident-1", "Resident"),
    "intake_clerk_headers": build_user_headers("test-clerk-1", "IntakeClerk"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "AbatementCoordinator"),
    "inventory_manager_headers": build_user_headers("test-inventory-1", "InventoryManager"),
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    # entity_backed fallbacks — ONLY for non-ownership tests (e.g. unauthorized-role checks).
    "crew_lead_headers": build_user_headers("test-crewlead-1", "CrewLead"),
    "property_owner_headers": build_user_headers("test-owner-1", "PropertyOwnerUser"),
}


# Per-instance builders — mandatory for entity_backed roles when the call is
# ownership-gated. Pass the actual persisted entity id as user_id.
def make_crew_lead_headers(crew_id: str) -> dict:
    """For CrewLead (entity_backed:Crew). Pass the owning Crew.id whenever the
    call (start / complete / photo upload) is ownership-gated."""
    return build_user_headers(crew_id, "CrewLead")


def make_property_owner_headers(owner_id: str) -> dict:
    """For PropertyOwnerUser (entity_backed:PropertyOwner). Pass the owning
    PropertyOwner.id whenever the call (consent / dispute / pay) is ownership-gated."""
    return build_user_headers(owner_id, "PropertyOwnerUser")
