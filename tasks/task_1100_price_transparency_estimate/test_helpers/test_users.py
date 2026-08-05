"""Pre-built role headers for every role in the PRD.

ProviderStaff / PayerAnalyst / Admin carry opaque operator identifiers not
tied to any persisted entity. A PatientUser's X-User-ID is the acting
Patient.id, so ownership-gated calls (accept, dispute, cancel, own-resource
reads) MUST use make_patient_headers(patient_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# patient ownership.
TEST_USERS = {
    "provider_staff_headers": build_user_headers("provider-1", "ProviderStaff"),
    "payer_analyst_headers": build_user_headers("payer-1", "PayerAnalyst"),
    "admin_headers": build_user_headers("admin-1", "Admin"),
    # Fallback only; PatientUser ownership calls need make_patient_headers().
    "patient_headers": build_user_headers("patient-placeholder", "PatientUser"),
}


def make_provider_staff_headers(user_id: str = "provider-1") -> dict:
    """ProviderStaff (opaque). user_id is a free operator identifier."""
    return build_user_headers(user_id, "ProviderStaff")


def make_payer_analyst_headers(user_id: str = "payer-1") -> dict:
    """PayerAnalyst (opaque). user_id is a free operator identifier."""
    return build_user_headers(user_id, "PayerAnalyst")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """Admin (opaque). user_id is a free operator identifier."""
    return build_user_headers(user_id, "Admin")


def make_patient_headers(patient_id: str) -> dict:
    """PatientUser (entity_backed:Patient). Pass the actual Patient.id; the
    server compares a resource's patient foreign key to this X-User-ID for
    ownership checks."""
    return build_user_headers(patient_id, "PatientUser")
