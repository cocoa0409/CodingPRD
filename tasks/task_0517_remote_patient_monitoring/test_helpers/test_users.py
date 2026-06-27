"""Pre-built role headers for every role in the PRD.

Per §2.1 all five roles carry an OPAQUE identity: X-User-ID is an operator
identifier never compared to any entity's id. Shared constants are therefore the
canonical form. The make_*_headers builders exist for tests that must pin a
specific X-User-ID into a recorded provenance field (acknowledged_by_user_id,
reviewer_user_id, clinician_user_id) — e.g. segregation-of-duties and task-owner
checks (§2.11), which compare these recorded user-id fields to one another.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "care_coordinator_headers": build_user_headers("cc-1", "CareCoordinator"),
    "clinician_headers": build_user_headers("clin-1", "Clinician"),
    "physician_headers": build_user_headers("phys-1", "Physician"),
    "billing_specialist_headers": build_user_headers("bill-1", "BillingSpecialist"),
    "payer_agent_headers": build_user_headers("payer-1", "PayerAgent"),
}


def make_care_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CareCoordinator")


def make_clinician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Clinician")


def make_physician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Physician")


def make_billing_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingSpecialist")


def make_payer_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PayerAgent")
