"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed (ReferringPhysician -> Physician, RehabClinician ->
Clinician); ownership-gated calls MUST use the per-instance builders with the
actual entity id. RehabCoordinator and BillingSpecialist are opaque operators.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# entity ownership (e.g. GET reads, 404-on-missing).
TEST_USERS = {
    "coordinator_headers": build_user_headers("op-coordinator-1", "RehabCoordinator"),
    "billing_headers": build_user_headers("op-billing-1", "BillingSpecialist"),
    # Fallbacks for entity_backed roles on non-ownership calls only.
    "physician_headers": build_user_headers("test-physician-1", "ReferringPhysician"),
    "clinician_headers": build_user_headers("test-clinician-1", "RehabClinician"),
}


def make_coordinator_headers(user_id: str = "op-coordinator-1") -> dict:
    """RehabCoordinator (opaque operator)."""
    return build_user_headers(user_id, "RehabCoordinator")


def make_billing_headers(user_id: str = "op-billing-1") -> dict:
    """BillingSpecialist (opaque operator)."""
    return build_user_headers(user_id, "BillingSpecialist")


def make_physician_headers(user_id: str) -> dict:
    """ReferringPhysician (entity_backed:Physician). Pass the Physician.id as user_id
    for ownership-gated calls such as creating a referral."""
    return build_user_headers(user_id, "ReferringPhysician")


def make_clinician_headers(user_id: str) -> dict:
    """RehabClinician (entity_backed:Clinician). Pass the Clinician.id as user_id
    for ownership-gated calls such as completing a session or recording outcomes."""
    return build_user_headers(user_id, "RehabClinician")
