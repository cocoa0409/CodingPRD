"""Pre-built role headers for every role in the PRD (§2.1).

Every role's X-User-ID is an opaque operator identifier, never compared to a
persisted entity id; the only identity-sensitive rule is segregation of duties,
which compares the releasing officer's X-User-ID against the claim's recorded
approver_user_id. Builders let tests pin specific user ids for that check.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "program_manager_headers": build_user_headers("test-pm-1", "ProgramManager"),
    "actuary_headers": build_user_headers("test-actuary-1", "Actuary"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "claims_adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    "treasury_officer_headers": build_user_headers("test-treasury-1", "TreasuryOfficer"),
    "fraud_analyst_headers": build_user_headers("test-fraud-1", "FraudAnalyst"),
    "data_operations_headers": build_user_headers("test-dataops-1", "DataOperations"),
    "servicing_agent_headers": build_user_headers("test-servicing-1", "ServicingAgent"),
}


def make_program_manager_headers(user_id: str = "test-pm-1") -> dict:
    return build_user_headers(user_id, "ProgramManager")


def make_actuary_headers(user_id: str = "test-actuary-1") -> dict:
    return build_user_headers(user_id, "Actuary")


def make_underwriter_headers(user_id: str = "test-underwriter-1") -> dict:
    return build_user_headers(user_id, "Underwriter")


def make_claims_adjuster_headers(user_id: str = "test-adjuster-1") -> dict:
    """ClaimsAdjuster headers with a pinned user id; the id is recorded as
    approver_user_id at claim approval (PRD §2.9)."""
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_treasury_officer_headers(user_id: str = "test-treasury-1") -> dict:
    """TreasuryOfficer headers with a pinned user id; release-payment compares
    this id against the claim's approver_user_id (PRD §2.9)."""
    return build_user_headers(user_id, "TreasuryOfficer")


def make_fraud_analyst_headers(user_id: str = "test-fraud-1") -> dict:
    return build_user_headers(user_id, "FraudAnalyst")


def make_data_operations_headers(user_id: str = "test-dataops-1") -> dict:
    return build_user_headers(user_id, "DataOperations")


def make_servicing_agent_headers(user_id: str = "test-servicing-1") -> dict:
    return build_user_headers(user_id, "ServicingAgent")
