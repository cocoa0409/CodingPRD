"""Pre-built role headers for every role in the PRD.

ClinicAdmin and Pharmacist are opaque roles — their X-User-ID is not tied to any
persisted entity, so the shared-constant form is canonical for them.

Practitioner and Patient are entity_backed roles — their X-User-ID must equal the
owning entity's id whenever the call is ownership-gated. For those, use the
per-instance builders make_practitioner_headers(id) / make_patient_headers(id)
with the real entity id. The shared constants are a fallback only for tests that
do NOT exercise ownership (e.g. 400-on-bad-payload, 404-on-missing-resource).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # opaque roles — shared constant is the canonical form
    "clinic_admin_headers": build_user_headers("test-admin-1", "ClinicAdmin"),
    "pharmacist_headers": build_user_headers("test-pharmacist-1", "Pharmacist"),
    # entity_backed roles — shared constant is a non-ownership fallback only
    "practitioner_headers": build_user_headers("test-practitioner-1", "Practitioner"),
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
}


# ─── Per-instance builders for entity_backed roles ────────────────────────
def make_practitioner_headers(user_id: str) -> dict:
    """For Practitioner (entity_backed:Practitioner). Pass the actual Practitioner.id
    as user_id whenever the call is ownership-gated (plan/intake/appointment-complete)."""
    return build_user_headers(user_id, "Practitioner")


def make_patient_headers(user_id: str) -> dict:
    """For Patient (entity_backed:Patient). Pass the actual Patient.id as user_id
    whenever the call reads that patient's own clinical/billing records."""
    return build_user_headers(user_id, "Patient")
