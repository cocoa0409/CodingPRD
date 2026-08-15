"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "trader_headers": build_user_headers("test-trader-1", "Trader"),
    "analyst_headers": build_user_headers("test-analyst-1", "SettlementAnalyst"),
    "credit_headers": build_user_headers("test-credit-1", "CreditOfficer"),
    # opaque role: shared constant is the canonical form.
    "iso_headers": build_user_headers("test-iso-1", "IsoOperator"),
}


# Per-instance builders — required for every entity_backed role.
def make_trader_headers(user_id: str) -> dict:
    """For Trader (entity_backed:MarketParticipant). Pass the actual participant id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Trader")


def make_analyst_headers(user_id: str) -> dict:
    """For SettlementAnalyst (entity_backed:MarketParticipant). Pass the actual
    participant id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "SettlementAnalyst")


def make_credit_headers(user_id: str) -> dict:
    """For CreditOfficer (entity_backed:MarketParticipant). Pass the actual
    participant id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "CreditOfficer")


def make_iso_headers(user_id: str = "test-iso-op") -> dict:
    """For IsoOperator (opaque). Any opaque identifier works."""
    return build_user_headers(user_id, "IsoOperator")
