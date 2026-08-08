"""Pre-built role headers for every role in the PRD (§2.1).

Patient and Provider are entity-backed: their X-User-ID is the id of the
acting entity, and ownership checks compare that id to the resource's patient/
provider foreign key. For ownership-gated calls always use the per-instance
builders make_patient_headers(patient_id) / make_provider_headers(provider_id).

BillingAdmin and CareCoordinator are opaque operator identities not tied to any
persisted entity, so their shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Entity-backed roles: shared constants are a fallback for tests that do
    # NOT exercise ownership (e.g. 401/403 short-circuits before ownership).
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
    # Opaque roles: shared constant is the canonical form.
    "billing_admin_headers": build_user_headers("test-billing-1", "BillingAdmin"),
    "care_coordinator_headers": build_user_headers("test-coordinator-1", "CareCoordinator"),
}


def make_patient_headers(user_id: str) -> dict:
    """For Patient (entity_backed:Patient). Pass the actual Patient.id whenever
    the call is ownership-gated."""
    return build_user_headers(user_id, "Patient")


def make_provider_headers(user_id: str) -> dict:
    """For Provider (entity_backed:Provider). Pass the actual Provider.id
    whenever the call is ownership-gated (e.g. prescription provider_id)."""
    return build_user_headers(user_id, "Provider")


def billing_admin_headers() -> dict:
    return TEST_USERS["billing_admin_headers"]


def care_coordinator_headers() -> dict:
    return TEST_USERS["care_coordinator_headers"]
