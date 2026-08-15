"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. The AccreditedVet role is entity_backed by Veterinarian, so its
# shared constant is only a fallback for non-ownership tests.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "officer_headers": build_user_headers("officer-a", "StateVetOfficer"),
    "officer_b_headers": build_user_headers("officer-b", "StateVetOfficer"),
    "vet_headers": build_user_headers("test-vet-1", "AccreditedVet"),
    "lab_headers": build_user_headers("test-lab-1", "LabTechnician"),
    "auditor_headers": build_user_headers("test-auditor-1", "StateAuditor"),
}


def make_vet_headers(user_id: str) -> dict:
    """For AccreditedVet (entity_backed: Veterinarian). Pass the actual
    Veterinarian.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "AccreditedVet")


def make_officer_headers(user_id: str) -> dict:
    """For StateVetOfficer (opaque identity). Distinct user ids matter for the
    quarantine-lift segregation-of-duties check (PRD §3.7)."""
    return build_user_headers(user_id, "StateVetOfficer")
