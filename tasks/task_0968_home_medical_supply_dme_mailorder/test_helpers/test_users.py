"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for opaque roles (X-User-ID is never compared to an entity id),
# and a fallback for the entity-backed Patient role in non-ownership tests only.
TEST_USERS = {
    # entity_backed:Patient — fallback ONLY for tests that do not exercise ownership.
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
    # opaque roles — canonical form.
    "intake_coordinator_headers": build_user_headers("test-intake-1", "IntakeCoordinator"),
    "prior_auth_specialist_headers": build_user_headers("test-pa-specialist-1", "PriorAuthSpecialist"),
    "fulfillment_agent_headers": build_user_headers("test-fulfillment-1", "FulfillmentAgent"),
    "billing_specialist_headers": build_user_headers("test-billing-1", "BillingSpecialist"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_patient_headers(user_id: str) -> dict:
    """For Patient (entity_backed:Patient). Pass the actual Patient.id as user_id
    whenever the call is ownership-gated (own orders, own programs, own reads)."""
    return build_user_headers(user_id, "Patient")
