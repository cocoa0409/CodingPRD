"""Pre-built role headers for every role in the PRD.

FrontOffice / Biller / BillingManager carry opaque operator identifiers not
tied to any persisted entity. Patient's X-User-ID is the acting Patient.id, so
ownership-gated calls MUST use make_patient_headers(patient_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and non-ownership tests.
TEST_USERS = {
    "frontoffice_headers": build_user_headers("front-1", "FrontOffice"),
    "biller_headers": build_user_headers("biller_alice", "Biller"),
    "manager_headers": build_user_headers("mgr_bob", "BillingManager"),
    # Fallback only; Patient calls that touch owned resources need make_patient_headers.
    "patient_headers": build_user_headers("patient-placeholder", "Patient"),
}


def make_frontoffice_headers(user_id: str = "front-1") -> dict:
    """FrontOffice (opaque). user_id is a free operator identifier."""
    return build_user_headers(user_id, "FrontOffice")


def make_biller_headers(user_id: str = "biller_alice") -> dict:
    """Biller (opaque). user_id anchors the segregation-of-duties check."""
    return build_user_headers(user_id, "Biller")


def make_manager_headers(user_id: str = "mgr_bob") -> dict:
    """BillingManager (opaque)."""
    return build_user_headers(user_id, "BillingManager")


def make_patient_headers(patient_id: str) -> dict:
    """Patient (entity_backed:Patient). Pass the actual Patient.id; ownership
    checks compare resource.patient_id to this X-User-ID."""
    return build_user_headers(patient_id, "Patient")
