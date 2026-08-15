"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque staff roles, and for Investor tests whose
# success does NOT depend on ownership of the subject resource.
TEST_USERS = {
    # Opaque staff roles: shared constant is the canonical form.
    "fund_admin_headers": build_user_headers("test-fund-admin-1", "FundAdmin"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "transfer_agent_headers": build_user_headers("test-transfer-agent-1", "TransferAgent"),
    "portfolio_manager_headers": build_user_headers("test-portfolio-manager-1", "PortfolioManager"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only
    # (e.g., asserting ERR_FORBIDDEN on behalf of a non-owner investor).
    "investor_headers": build_user_headers("test-investor-1", "Investor"),
}


# Per-instance builders — required for every entity_backed role.
def make_investor_headers(user_id: str) -> dict:
    """For Investor (entity_backed:Investor). Pass the actual Investor.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Investor")
