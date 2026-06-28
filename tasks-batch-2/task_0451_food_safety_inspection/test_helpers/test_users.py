"""Pre-built role headers for every role in the PRD (Food Safety Inspection API).

PRD §2.1: PermitClerk, EnforcementOfficer, and HealthDirector carry an opaque
operator identity never compared to an entity id. The Inspector role is
entity-backed: X-User-ID is the id of the acting Inspector row, and ownership
checks compare a resource's inspector foreign key to X-User-ID. Tests whose
success depends on the inspector owning the inspection MUST use
make_inspector_headers(inspector["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# Inspector ownership (e.g. 400-on-bad-payload, 403-forbidden-role checks).
TEST_USERS = {
    "permit_clerk_headers": build_user_headers("test-permit-clerk-1", "PermitClerk"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "enforcement_officer_headers": build_user_headers("test-enforcement-1", "EnforcementOfficer"),
    "health_director_headers": build_user_headers("test-director-1", "HealthDirector"),
}


# Per-instance builder — required for the entity_backed Inspector role.
def make_inspector_headers(inspector_id: str) -> dict:
    """For the Inspector role (entity_backed:Inspector). Pass the actual
    Inspector.id as user_id whenever the call is ownership-gated (start/complete/
    reopen/finalize an inspection, record/delete violations, dispatch routes,
    dispatch complaints)."""
    return build_user_headers(inspector_id, "Inspector")
