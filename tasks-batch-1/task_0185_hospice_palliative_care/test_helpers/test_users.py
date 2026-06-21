"""Pre-built role headers for every role in the hospice & palliative care PRD.

Three roles (IntakeCoordinator, ClinicalManager, BillingAdmin) are opaque operator
identifiers — the shared-constant form is canonical for them. The Physician role is
entity-backed: X-User-ID must be the acting Physician entity's id, so any call that
names a physician (a certification) uses make_physician_headers(physician_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles use these everywhere; the entity-backed
# physician_headers constant is a fallback for tests whose success does not depend
# on the X-User-ID matching a real Physician id.
TEST_USERS = {
    "intake_headers": build_user_headers("test-intake-1", "IntakeCoordinator"),
    "clinical_headers": build_user_headers("test-clinical-1", "ClinicalManager"),
    "billing_headers": build_user_headers("test-billing-1", "BillingAdmin"),
    "physician_headers": build_user_headers("test-physician-1", "Physician"),
}


def make_physician_headers(physician_id: str) -> dict:
    """For Physician (entity_backed:Physician). Pass the actual Physician.id as
    user_id whenever the call references that physician (e.g., a certification
    naming certifying_physician_id)."""
    return build_user_headers(physician_id, "Physician")
