"""Pre-built role headers for every role in the PRD.

Three roles (ClinicAdmin, Audiologist, BillingClerk) are opaque operator
identities; their X-User-ID is never compared to any entity id, so the shared
constant form is canonical for them. The Patient role is entity-backed: its
X-User-ID must equal the acting Patient.id, so ownership-gated Patient calls
MUST use make_patient_headers(patient_id) with the real patient id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constant is the canonical form.
    "clinic_admin_headers": build_user_headers("admin-op-1", "ClinicAdmin"),
    "audiologist_headers": build_user_headers("aud-op-1", "Audiologist"),
    "billing_clerk_headers": build_user_headers("clerk-op-1", "BillingClerk"),
    # Entity-backed Patient role — shared constant is a fallback only for tests
    # that do NOT exercise ownership (e.g. a 403/404 before the ownership check).
    "patient_headers": build_user_headers("patient-placeholder-1", "Patient"),
}


def make_clinic_admin_headers(user_id: str = "admin-op-1") -> dict:
    return build_user_headers(user_id, "ClinicAdmin")


def make_audiologist_headers(user_id: str = "aud-op-1") -> dict:
    return build_user_headers(user_id, "Audiologist")


def make_billing_clerk_headers(user_id: str = "clerk-op-1") -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_patient_headers(user_id: str) -> dict:
    """For the Patient role (entity_backed:Patient). Pass the actual Patient.id
    as user_id whenever the call is ownership-gated (appeal, pause, resume,
    cancel subscription, skip cycle, create own subscription/claim)."""
    return build_user_headers(user_id, "Patient")
