"""Pre-built role headers for every role in the PRD (§2.1).

FundManager, ComplianceOfficer, Operator and Anonymous are opaque: X-User-ID is an operator
identifier never compared to any entity id, so a shared constant is the canonical form.

Investor is entity_backed: X-User-ID must equal the acting Investor's id on ownership-gated
calls, so consumers must thread the real investor id through make_investor_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

# Distinct fixed ids so segregation-of-duties (FundManager vs ComplianceOfficer) is observable.
FUND_MANAGER_USER_ID = "fm-1"
COMPLIANCE_OFFICER_USER_ID = "co-1"
OPERATOR_USER_ID = "op-1"

# Shared constants — safe for opaque roles, and for Investor tests that do NOT exercise
# ownership (e.g. 404-on-missing-resource).
TEST_USERS = {
    "fund_manager_headers": build_user_headers(FUND_MANAGER_USER_ID, "FundManager"),
    "compliance_officer_headers": build_user_headers(COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"),
    "operator_headers": build_user_headers(OPERATOR_USER_ID, "Operator"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # entity_backed fallback — for non-ownership investor tests only.
    "investor_headers": build_user_headers("test-investor-1", "Investor"),
}


# Per-instance builders.
def make_fund_manager_headers(user_id: str = FUND_MANAGER_USER_ID) -> dict:
    """FundManager (opaque)."""
    return build_user_headers(user_id, "FundManager")


def make_compliance_officer_headers(user_id: str = COMPLIANCE_OFFICER_USER_ID) -> dict:
    """ComplianceOfficer (opaque). Id is recorded into reviewed_by_user_id on suitability review."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_operator_headers(user_id: str = OPERATOR_USER_ID) -> dict:
    """Operator (opaque)."""
    return build_user_headers(user_id, "Operator")


def make_investor_headers(user_id: str) -> dict:
    """Investor (entity_backed:Investor). Pass the actual Investor.id as user_id whenever the
    call is ownership-gated (own subscriptions, redemptions, holdings)."""
    return build_user_headers(user_id, "Investor")


def make_anonymous_headers(user_id: str = "anon-1") -> dict:
    """Anonymous (opaque). Used for investor self-registration."""
    return build_user_headers(user_id, "Anonymous")
