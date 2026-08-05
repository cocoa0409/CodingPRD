"""Pre-built role headers for every role in the PRD.

Five of the six roles carry an opaque identity (X-User-ID is a free operator id
that the server never compares to any record). The Surgeon role is entity-backed:
its X-User-ID must equal the acting Surgeon record's id, so ownership-gated calls
MUST use make_surgeon_headers(surgeon_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# surgeon ownership (e.g. 401/403/404 checks).
TEST_USERS = {
    "program_coordinator_headers": build_user_headers("op-coordinator-1", "ProgramCoordinator"),
    "dietitian_headers": build_user_headers("op-dietitian-1", "Dietitian"),
    "behavioral_health_headers": build_user_headers("op-bh-1", "BehavioralHealthClinician"),
    "billing_specialist_headers": build_user_headers("op-billing-1", "BillingSpecialist"),
    "system_admin_headers": build_user_headers("op-admin-1", "SystemAdmin"),
    # Fallback surgeon constant for non-ownership tests (e.g. 404 on missing case).
    "surgeon_headers": build_user_headers("op-surgeon-1", "Surgeon"),
}


def make_surgeon_headers(user_id: str) -> dict:
    """For the Surgeon role (entity_backed:Surgeon). Pass the acting Surgeon's id
    as user_id on any ownership-gated call (complete/complications/resolve)."""
    return build_user_headers(user_id, "Surgeon")
