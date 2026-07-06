"""Pre-built role headers for every role in the PRD.

Roles Investigator, Pathologist, and MedicalExaminer are entity-backed (X-User-ID must
resolve to an existing Investigator/Pathologist record). Use the per-instance builders
below with a real entity id for any ownership- or identity-gated call. The shared
TEST_USERS constants are safe only for opaque roles (Admin, LabTech, Anonymous) or for
tests that do not exercise entity-identity resolution.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "labtech_headers": build_user_headers("test-labtech-1", "LabTech"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # Entity-backed roles — shared constants are a fallback for non-identity tests only.
    "investigator_headers": build_user_headers("test-investigator-1", "Investigator"),
    "pathologist_headers": build_user_headers("test-pathologist-1", "Pathologist"),
    "medical_examiner_headers": build_user_headers("test-me-1", "MedicalExaminer"),
}


def make_investigator_headers(user_id: str) -> dict:
    """For Investigator (entity_backed:Investigator). Pass the actual Investigator.id."""
    return build_user_headers(user_id, "Investigator")


def make_pathologist_headers(user_id: str) -> dict:
    """For Pathologist (entity_backed:Pathologist). Pass the actual Pathologist.id."""
    return build_user_headers(user_id, "Pathologist")


def make_medical_examiner_headers(user_id: str) -> dict:
    """For MedicalExaminer (entity_backed:Pathologist). Pass the actual (ME) Pathologist.id."""
    return build_user_headers(user_id, "MedicalExaminer")


def make_labtech_headers(user_id: str = "test-labtech-1") -> dict:
    """For LabTech (opaque)."""
    return build_user_headers(user_id, "LabTech")


def admin_headers() -> dict:
    return TEST_USERS["admin_headers"]
