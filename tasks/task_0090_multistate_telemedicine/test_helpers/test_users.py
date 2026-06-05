"""Pre-built role headers for every role in the PRD (§2.1).

Two kinds of entries per role:
  * a shared-constant entry in TEST_USERS — safe for opaque roles and for tests
    whose success does NOT depend on the caller owning the subject resource
    (400/404/403 negative tests, opaque-role calls).
  * a per-instance builder make_<role>_headers(user_id) — MANDATORY for the
    entity_backed roles Physician and Patient: pass the real entity id so
    ownership checks (Visit.physician_id / Visit.patient_id == X-User-ID) pass.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # entity_backed roles — shared constant is a fallback for NON-ownership tests only.
    "physician_headers": build_user_headers("test-physician-1", "Physician"),
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
    # opaque roles — the shared constant is the canonical form.
    "licensing_board_headers": build_user_headers("test-board-1", "LicensingBoard"),
    "compliance_officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


# ── Per-instance builders for entity_backed roles ──────

def make_physician_headers(physician_id: str) -> dict:
    """For Physician (entity_backed:Physician). Pass the acting Physician.id so a
    Physician acts only on a Visit whose physician_id equals X-User-ID (PRD §2.1)."""
    return build_user_headers(physician_id, "Physician")


def make_patient_headers(patient_id: str) -> dict:
    """For Patient (entity_backed:Patient). Pass the acting Patient.id so a Patient
    acts only on a Visit whose patient_id equals X-User-ID (PRD §2.1)."""
    return build_user_headers(patient_id, "Patient")


# ── Opaque-role convenience headers ────────────────────

def board_headers() -> dict:
    return TEST_USERS["licensing_board_headers"]


def officer_headers() -> dict:
    return TEST_USERS["compliance_officer_headers"]


def anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]
