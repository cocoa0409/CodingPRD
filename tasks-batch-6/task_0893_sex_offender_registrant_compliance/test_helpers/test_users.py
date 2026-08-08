"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (RegistryAdmin, RegistrationOfficer,
# ComplianceReviewer whose X-User-ID is not tied to any entity), and for tests
# that do not exercise Registrant ownership.
TEST_USERS = {
    "registry_admin_headers": build_user_headers("test-admin-1", "RegistryAdmin"),
    "registration_officer_headers": build_user_headers("test-officer-1", "RegistrationOfficer"),
    "compliance_reviewer_headers": build_user_headers("test-reviewer-1", "ComplianceReviewer"),
    # Fallback only; the Registrant role is entity-backed — ownership-gated calls
    # must use make_registrant_headers(registrant_id) below.
    "registrant_headers": build_user_headers("test-registrant-1", "Registrant"),
}


def make_registrant_headers(user_id: str) -> dict:
    """For the Registrant role (entity_backed:Registrant). Pass the actual
    Registrant.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Registrant")
