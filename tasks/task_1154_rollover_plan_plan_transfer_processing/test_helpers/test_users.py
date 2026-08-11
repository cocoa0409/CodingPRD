"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# Participant ownership scoping.
TEST_USERS = {
    # entity_backed role (Participant): fallback for non-ownership contexts only.
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
    # opaque roles: canonical shared form.
    "admin_headers": build_user_headers("test-admin-1", "PlanSponsorAdmin"),
    "processor_headers": build_user_headers("proc-1", "RolloverProcessor"),
    "tax_officer_headers": build_user_headers("tax-1", "TaxReportingOfficer"),
    "operations_headers": build_user_headers("ops-1", "OperationsAgent"),
}


def make_participant_headers(user_id: str) -> dict:
    """Participant is entity-backed: X-User-ID must be the Participant entity's id
    for any ownership-gated call."""
    return build_user_headers(user_id, "Participant")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlanSponsorAdmin")


def make_processor_headers(user_id: str) -> dict:
    """RolloverProcessor is opaque, but the server records X-User-ID as
    eligibility_decided_by / reviewed_by and enforces segregation of duties,
    so the processor identity matters."""
    return build_user_headers(user_id, "RolloverProcessor")


def make_tax_officer_headers(user_id: str = "tax-1") -> dict:
    return build_user_headers(user_id, "TaxReportingOfficer")


def make_operations_headers(user_id: str = "ops-1") -> dict:
    return build_user_headers(user_id, "OperationsAgent")
