"""Pre-built role headers for every role in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

from .constants import ADMIN_USER_ID, FINANCE_USER_ID, FRAUD_USER_ID, PROCESSOR_USER_ID

# Shared constants.
#
# The four staff roles are opaque operator identifiers never compared to any
# entity id, so the shared constants below are the canonical form for them.
# Dealer and Consumer identify the acting Claimant by its id, so their shared
# constants are only safe for tests that do not exercise an ownership check
# (for example 404-on-missing-resource probes).
TEST_USERS = {
    "program_admin_headers": build_user_headers(ADMIN_USER_ID, "ProgramAdmin"),
    "claims_processor_headers": build_user_headers(PROCESSOR_USER_ID, "ClaimsProcessor"),
    "finance_officer_headers": build_user_headers(FINANCE_USER_ID, "FinanceOfficer"),
    "fraud_analyst_headers": build_user_headers(FRAUD_USER_ID, "FraudAnalyst"),
    "dealer_headers": build_user_headers("test-dealer-1", "Dealer"),
    "consumer_headers": build_user_headers("test-consumer-1", "Consumer"),
}


# --------------------------------------------------------------------------- #
# Per-instance builders
# --------------------------------------------------------------------------- #

def make_dealer_headers(claimant_id: str) -> dict:
    """For the Dealer role: X-User-ID is the id of the acting Claimant."""
    return build_user_headers(claimant_id, "Dealer")


def make_consumer_headers(claimant_id: str) -> dict:
    """For the Consumer role: X-User-ID is the id of the acting Claimant."""
    return build_user_headers(claimant_id, "Consumer")


def make_claimant_headers(claimant: dict) -> dict:
    """Pick the claimant-facing role matching a claimant's type."""
    if claimant["type"] == "DEALER":
        return make_dealer_headers(claimant["id"])
    return make_consumer_headers(claimant["id"])


def make_processor_headers(user_id: str) -> dict:
    """A ClaimsProcessor acting under a specific operator id (segregation of duties)."""
    return build_user_headers(user_id, "ClaimsProcessor")


def make_finance_headers(user_id: str) -> dict:
    """A FinanceOfficer acting under a specific operator id (segregation of duties)."""
    return build_user_headers(user_id, "FinanceOfficer")
