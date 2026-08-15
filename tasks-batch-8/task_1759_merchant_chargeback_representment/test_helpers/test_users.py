"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# merchant ownership. For ownership-gated merchant-side calls, use
# make_merchant_user_headers(merchant["id"]) instead of the shared constant.
TEST_USERS = {
    # entity_backed role (MerchantUser identity IS the Merchant.id): shared
    # constant is a fallback for non-ownership tests only.
    "merchant_user_headers": build_user_headers("test-merchant-user-1", "MerchantUser"),
    # opaque roles: shared constants are the canonical form.
    "acquirer_ops_headers": build_user_headers("test-acquirer-ops-1", "AcquirerOps"),
    "risk_officer_headers": build_user_headers("test-risk-officer-1", "RiskOfficer"),
    "finance_ops_headers": build_user_headers("test-finance-ops-1", "FinanceOps"),
}


def make_merchant_user_headers(user_id: str) -> dict:
    """For MerchantUser (entity_backed: Merchant). Pass the actual Merchant.id
    as user_id whenever the call is ownership-gated (PRD §2.1/§2.7)."""
    return build_user_headers(user_id, "MerchantUser")


def make_acquirer_ops_headers(user_id: str) -> dict:
    """AcquirerOps is an opaque role; the id is recorded but never ownership-checked."""
    return build_user_headers(user_id, "AcquirerOps")


def make_risk_officer_headers(user_id: str) -> dict:
    """RiskOfficer is an opaque role; the id is recorded but never ownership-checked."""
    return build_user_headers(user_id, "RiskOfficer")


def make_finance_ops_headers(user_id: str) -> dict:
    """FinanceOps is an opaque role; distinct ids matter for fee-waiver
    segregation of duties (PRD §3.8)."""
    return build_user_headers(user_id, "FinanceOps")
