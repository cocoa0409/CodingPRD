"""Pre-built role headers for every role in the PRD.

All roles in this service are opaque: X-User-ID is an operator identifier,
never compared to any entity id. Shared constants are therefore the canonical
form; the per-instance builders exist for tests that must control the operator
id (e.g. segregation-of-duties scenarios).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "intake_coordinator_headers": build_user_headers("test-intake-1", "IntakeCoordinator"),
    "vision_specialist_headers": build_user_headers("test-specialist-1", "VisionSpecialist"),
    "funding_coordinator_headers": build_user_headers("fc-1", "FundingCoordinator"),
    "payer_adjudicator_headers": build_user_headers("pa-1", "PayerAdjudicator"),
    "billing_specialist_headers": build_user_headers("bs-1", "BillingSpecialist"),
    "repair_technician_headers": build_user_headers("test-tech-1", "RepairTechnician"),
    "clinic_admin_headers": build_user_headers("test-admin-1", "ClinicAdmin"),
}

# Anonymous: both headers blank -> ERR_UNAUTHENTICATED
ANONYMOUS_HEADERS = {"X-User-ID": "", "X-User-Role": ""}


def make_intake_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_vision_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "VisionSpecialist")


def make_funding_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FundingCoordinator")


def make_payer_adjudicator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PayerAdjudicator")


def make_billing_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingSpecialist")


def make_repair_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RepairTechnician")


def make_clinic_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClinicAdmin")
