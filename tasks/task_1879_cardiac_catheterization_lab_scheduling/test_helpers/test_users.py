"""Pre-built role headers for every role in the PRD (§2.1).

Identity rules (PRD §2.1): for InterventionalCardiologist and
CathLabTechnologist, X-User-ID is the id of the acting StaffMember and is
compared against staff-referencing foreign keys. For CathLabScheduler,
RecoveryNurseManager, and RegistryCoordinator, X-User-ID is an opaque operator
identifier never compared to any entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400/404/403 paths, and all CathLabTechnologist calls: no endpoint
# in the PRD compares a technologist's X-User-ID to a resource field).
TEST_USERS = {
    "scheduler_headers": build_user_headers("test-scheduler-1", "CathLabScheduler"),
    # entity_backed: fallback for non-ownership contexts only.
    "cardiologist_headers": build_user_headers(
        "test-cardiologist-1", "InterventionalCardiologist"),
    # entity_backed: no ownership-gated technologist endpoint exists in the PRD,
    # so this shared constant is the canonical form for technologist calls.
    "technologist_headers": build_user_headers(
        "test-technologist-1", "CathLabTechnologist"),
    "nurse_manager_headers": build_user_headers(
        "test-nurse-manager-1", "RecoveryNurseManager"),
    "registry_coordinator_headers": build_user_headers(
        "test-registry-coordinator-1", "RegistryCoordinator"),
}


def make_interventional_cardiologist_headers(user_id: str) -> dict:
    """For InterventionalCardiologist (identity: the acting StaffMember's id).

    Pass the actual StaffMember.id whenever the call is ownership-gated —
    case start/complete (X-User-ID must equal performing_physician_id) and AUC
    attestation (X-User-ID must equal ordering_physician_id).
    """
    return build_user_headers(user_id, "InterventionalCardiologist")


def make_cath_technologist_headers(user_id: str) -> dict:
    """For CathLabTechnologist (identity: the acting StaffMember's id)."""
    return build_user_headers(user_id, "CathLabTechnologist")
