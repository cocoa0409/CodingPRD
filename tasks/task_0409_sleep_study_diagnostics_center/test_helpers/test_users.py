"""Pre-built role headers for every role in the PRD.

Four roles (SchedulingCoordinator, SleepTechnologist, Physician, DMECoordinator)
are opaque operator identities: X-User-ID is never matched against any entity id,
so the shared constant is the canonical form for every call.

The Patient role is entity-backed: X-User-ID must equal the acting Patient's id for
ownership checks. Use make_patient_headers(patient_id) whenever an ownership-gated
call is made as a Patient.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "scheduling_coordinator_headers": build_user_headers(
        "test-coordinator-1", "SchedulingCoordinator"
    ),
    "sleep_technologist_headers": build_user_headers(
        "test-technologist-1", "SleepTechnologist"
    ),
    "physician_headers": build_user_headers("test-physician-1", "Physician"),
    "dme_coordinator_headers": build_user_headers(
        "test-dme-coordinator-1", "DMECoordinator"
    ),
    # Entity-backed role fallback — only for non-ownership tests.
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
}


def make_patient_headers(patient_id: str) -> dict:
    """For the Patient role (entity_backed:Patient). Pass the actual Patient.id as
    the user id whenever the call is ownership-gated."""
    return build_user_headers(patient_id, "Patient")
