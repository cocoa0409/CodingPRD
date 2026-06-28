"""Pre-built role headers for every role in the PRD.

The only entity-backed role is Bettor: its X-User-ID must equal the Account.id
it acts on (PRD §2.1). For ownership-gated calls, use make_bettor_headers(account_id).
TradingOps, SettlementAgent, and ComplianceOfficer carry opaque operator
identifiers not tied to any persisted entity, so a shared constant is the
canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Bettor tests that do not
# exercise ownership (e.g. a placement that fails before the ownership check,
# or a forbidden-role probe).
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "bettor_headers": build_user_headers("test-bettor-1", "Bettor"),
    # opaque roles: shared constant is the canonical form.
    "trading_ops_headers": build_user_headers("test-trading-ops-1", "TradingOps"),
    "settlement_agent_headers": build_user_headers("test-settlement-agent-1", "SettlementAgent"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
}


def make_bettor_headers(account_id: str) -> dict:
    """For Bettor (entity_backed:Account). Pass the actual Account.id as user_id
    whenever the call is ownership-gated (deposits, withdrawals, geo-checks, bets,
    cash-out, bonus-claims, cooling-off/limit rg-controls, own-account reads)."""
    return build_user_headers(account_id, "Bettor")


def make_trading_ops_headers(user_id: str) -> dict:
    """TradingOps with a specific opaque operator id — used for SoD scenarios
    where the market setter id must be controlled."""
    return build_user_headers(user_id, "TradingOps")


def make_settlement_agent_headers(user_id: str) -> dict:
    """SettlementAgent with a specific opaque operator id — used for SoD
    scenarios (result poster vs market setter)."""
    return build_user_headers(user_id, "SettlementAgent")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer with a specific opaque operator id."""
    return build_user_headers(user_id, "ComplianceOfficer")


# Headers carrying no auth at all — for the missing-credentials test (PRD §2.1).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
