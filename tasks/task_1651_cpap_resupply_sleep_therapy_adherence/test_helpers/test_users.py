"""Pre-built role headers for every role in the PRD.

All four roles use opaque operator identifiers (PRD §2.1): X-User-ID is not
tied to any persisted entity, so the shared constants are the canonical form.
The make_* builders exist for tests that need a specific operator id — e.g.
segregation-of-duties tests where the authorizer's X-User-ID must equal the
clearing clinician's recorded id (PRD §2.9).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "ops_admin_headers": build_user_headers("ops-admin-1", "OpsAdmin"),
    "intake_coordinator_headers": build_user_headers("intake-1", "IntakeCoordinator"),
    "respiratory_therapist_headers": build_user_headers("rt-1", "RespiratoryTherapist"),
    "billing_specialist_headers": build_user_headers("bs-1", "BillingSpecialist"),
}


def make_ops_admin_headers(user_id: str = "ops-admin-1") -> dict:
    return build_user_headers(user_id, "OpsAdmin")


def make_intake_coordinator_headers(user_id: str = "intake-1") -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_respiratory_therapist_headers(user_id: str = "rt-1") -> dict:
    return build_user_headers(user_id, "RespiratoryTherapist")


def make_billing_specialist_headers(user_id: str = "bs-1") -> dict:
    return build_user_headers(user_id, "BillingSpecialist")
