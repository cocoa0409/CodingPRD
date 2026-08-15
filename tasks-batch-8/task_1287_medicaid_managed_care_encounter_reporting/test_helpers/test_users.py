"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "state_agency_headers": build_user_headers("test-state-1", "StateAgency"),
    "mco_encounter_ops_headers": build_user_headers("test-ops-1", "McoEncounterOps"),
    "mco_compliance_headers": build_user_headers("test-comp-1", "McoCompliance"),
    "mco_finance_headers": build_user_headers("test-finance-1", "McoFinance"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "delegated_submitter_headers": build_user_headers("test-submitter-1", "DelegatedSubmitter"),
}


# Per-instance builders — required for entity_backed roles.
def make_delegated_submitter_headers(user_id: str) -> dict:
    """For DelegatedSubmitter (entity_backed:Submitter). Pass the actual Submitter.id
    as user_id whenever the call is ownership-gated (encounter intake with submitter_id)."""
    return build_user_headers(user_id, "DelegatedSubmitter")


# Opaque-role builders with a caller-chosen operator id. These matter for
# segregation-of-duties scenarios where the sealer/transmitter X-User-ID is asserted.
def make_state_agency_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StateAgency")


def make_mco_encounter_ops_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "McoEncounterOps")


def make_mco_compliance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "McoCompliance")


def make_mco_finance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "McoFinance")
