"""Pre-built role headers for every role in the PRD (section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. The Patient role is entity_backed (PRD 2.1: X-User-ID is the id of
# the acting Patient), so ownership-gated calls MUST use make_patient_headers
# with the actual Patient id.
TEST_USERS = {
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
    "nurse_headers": build_user_headers("nurse-1", "HomeNurse"),
    "nurse_2_headers": build_user_headers("nurse-2", "HomeNurse"),
    "nephrologist_headers": build_user_headers("nephro-1", "Nephrologist"),
    "coordinator_headers": build_user_headers("coord-1", "SupplyCoordinator"),
    "biomed_headers": build_user_headers("biomed-1", "BiomedTechnician"),
    "admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
}


# Per-instance builders.
def make_patient_headers(patient_id: str) -> dict:
    """Patient role is entity-backed: X-User-ID must equal the Patient id for
    ownership-gated writes (PRD 2.1)."""
    return build_user_headers(patient_id, "Patient")


def make_nurse_headers(user_id: str) -> dict:
    """HomeNurse is opaque; pass distinct ids to satisfy segregation-of-duties
    rules (PRD 2.11)."""
    return build_user_headers(user_id, "HomeNurse")


def make_nephrologist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Nephrologist")


def make_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SupplyCoordinator")


def make_biomed_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BiomedTechnician")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")
