"""Pre-built role headers for every role in the PRD.

Four roles are opaque: their `X-User-ID` is an operator identifier the server
records but never compares to any persisted row. Two roles are entity-backed —
`LabTechnician` carries the acting `DentalLab.id` and `Patient` carries the
acting `Patient.id` — so those two need a per-instance builder.
"""

from prd_bench_local_runner.testing import build_user_headers

# Stable operator identifiers for the four opaque roles.
PROSTHODONTIST_USER_ID = "dr-nunes"
SECOND_PROSTHODONTIST_USER_ID = "dr-halloran"
CLINICAL_DIRECTOR_USER_ID = "dir-okafor"
SECOND_CLINICAL_DIRECTOR_USER_ID = "dir-vasquez"
FRONT_OFFICE_USER_ID = "fo-lindgren"
PLATFORM_ADMIN_USER_ID = "admin-root"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "prosthodontist_headers": build_user_headers(PROSTHODONTIST_USER_ID, "Prosthodontist"),
    "clinical_director_headers": build_user_headers(CLINICAL_DIRECTOR_USER_ID, "ClinicalDirector"),
    "front_office_headers": build_user_headers(FRONT_OFFICE_USER_ID, "FrontOffice"),
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER_ID, "PlatformAdmin"),
    # Entity-backed roles — these shared constants are safe only for calls that
    # are not ownership-gated (role-refusal probes and the like).
    "lab_technician_headers": build_user_headers("test-lab-technician-1", "LabTechnician"),
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
}


def make_prosthodontist_headers(user_id: str) -> dict:
    """For a Prosthodontist acting under a specific operator identity."""
    return build_user_headers(user_id, "Prosthodontist")


def make_clinical_director_headers(user_id: str) -> dict:
    """For a ClinicalDirector acting under a specific operator identity.

    Segregation of duties compares this identity to the remake request's
    requested_by_user_id, so tests that exercise it must control the value.
    """
    return build_user_headers(user_id, "ClinicalDirector")


def make_front_office_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FrontOffice")


def make_lab_technician_headers(dental_lab_id: str) -> dict:
    """For a LabTechnician. Pass the acting DentalLab's id."""
    return build_user_headers(dental_lab_id, "LabTechnician")


def make_patient_headers(patient_id: str) -> dict:
    """For a Patient. Pass the acting Patient's id."""
    return build_user_headers(patient_id, "Patient")


def anonymous_headers() -> dict:
    """No X-User-ID and no X-User-Role at all."""
    return {"Content-Type": "application/json"}
