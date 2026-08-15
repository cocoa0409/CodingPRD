"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. For Cardholder (entity_backed) the shared constant is a fallback
# for non-ownership tests only; ownership-gated calls must use
# make_cardholder_headers(account_id).
TEST_USERS = {
    "cardholder_headers": build_user_headers("test-cardholder-1", "Cardholder"),
    "intake_agent_headers": build_user_headers("ops-ia-1", "IntakeAgent"),
    "investigator_headers": build_user_headers("ops-inv-1", "DisputeInvestigator"),
    "chargeback_analyst_headers": build_user_headers("ops-cb-1", "ChargebackAnalyst"),
    "finance_officer_headers": build_user_headers("ops-fin-1", "FinanceOfficer"),
    "bank_admin_headers": build_user_headers("ops-admin-1", "BankAdmin"),
}


def make_cardholder_headers(account_id: str) -> dict:
    """Cardholder identity is the CardAccount's id. Pass the real account id
    whenever the call is ownership-gated (intake, withdraw, own reads)."""
    return build_user_headers(account_id, "Cardholder")


def make_intake_agent_headers(user_id: str) -> dict:
    """IntakeAgent identity is opaque; the id is stamped as intake_agent_id."""
    return build_user_headers(user_id, "IntakeAgent")


def make_investigator_headers(user_id: str) -> dict:
    """DisputeInvestigator identity is opaque; compared against intake_agent_id
    by the segregation-of-duties rule on resolution."""
    return build_user_headers(user_id, "DisputeInvestigator")


def make_chargeback_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ChargebackAnalyst")


def make_finance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


def make_bank_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BankAdmin")
