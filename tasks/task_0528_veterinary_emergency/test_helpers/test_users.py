"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
# TriageNurse, ClinicianDVM, FinanceCoordinator all carry opaque operator identities:
# their X-User-ID is never compared against any entity id.
TEST_USERS = {
    "triage_nurse_headers": build_user_headers("nurse-1", "TriageNurse"),
    "clinician_dvm_headers": build_user_headers("dvm-1", "ClinicianDVM"),
    "finance_coordinator_headers": build_user_headers("finance-1", "FinanceCoordinator"),
    # Owner is entity_backed: the shared constant is a fallback only for non-ownership
    # tests (e.g. wrong-owner 403). Owner-gated success paths MUST use make_owner_headers.
    "owner_headers": build_user_headers("owner-shared", "Owner"),
}


# Per-instance builders.
def make_triage_nurse_headers(user_id: str = "nurse-1") -> dict:
    """Opaque TriageNurse identity."""
    return build_user_headers(user_id, "TriageNurse")


def make_clinician_dvm_headers(user_id: str = "dvm-1") -> dict:
    """Opaque ClinicianDVM identity; recorded as attending_dvm_id on begin-treatment/accept."""
    return build_user_headers(user_id, "ClinicianDVM")


def make_finance_coordinator_headers(user_id: str = "finance-1") -> dict:
    """Opaque FinanceCoordinator identity."""
    return build_user_headers(user_id, "FinanceCoordinator")


def make_owner_headers(owner_user_id: str) -> dict:
    """For Owner (entity_backed:Patient). Pass the patient's owner_user_id so the
    ownership check (patient.owner_user_id == X-User-ID) passes."""
    return build_user_headers(owner_user_id, "Owner")
