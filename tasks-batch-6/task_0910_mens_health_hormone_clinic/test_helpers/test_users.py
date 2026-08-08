"""Pre-built role headers for every role in the PRD (§2.1).

- ClinicAdmin identity is opaque: the shared constant is the canonical form.
- Clinician / Pharmacist / Patient identities are entity-backed: for any
  ownership-gated call, use the per-instance builder with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # ClinicAdmin: opaque operator identifier, never compared to an entity id.
    "clinic_admin_headers": build_user_headers("test-admin-1", "ClinicAdmin"),
    # Entity-backed roles: shared constants are fallbacks for non-ownership tests
    # (e.g. 403-on-role, 404-on-missing-resource) only.
    "clinician_headers": build_user_headers("test-clinician-1", "Clinician"),
    "pharmacist_headers": build_user_headers("test-pharmacist-1", "Pharmacist"),
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
}


def make_clinic_admin_headers(user_id: str = "test-admin-1") -> dict:
    """ClinicAdmin (opaque). Identifier is not tied to any entity."""
    return build_user_headers(user_id, "ClinicAdmin")


def make_clinician_headers(user_id: str) -> dict:
    """For Clinician (entity_backed:Clinician). Pass the real Clinician.id
    whenever the call is ownership-gated (plan activate/prescribe/titrate)."""
    return build_user_headers(user_id, "Clinician")


def make_pharmacist_headers(user_id: str) -> dict:
    """For Pharmacist (entity_backed:Pharmacist). Pass the real Pharmacist.id."""
    return build_user_headers(user_id, "Pharmacist")


def make_patient_headers(user_id: str) -> dict:
    """For Patient (entity_backed:Patient). Pass the real Patient.id."""
    return build_user_headers(user_id, "Patient")
