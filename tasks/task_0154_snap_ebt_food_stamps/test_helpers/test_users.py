"""Pre-built role headers for every role in the SNAP/EBT PRD.

Note: HouseholdHead and Merchant are entity_backed roles — X-User-ID must equal
the underlying entity id for ownership checks to pass. Use the make_*_headers()
helpers for ownership-gated calls; the shared TEST_USERS constants are a
fallback only for opaque roles or for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise ownership
TEST_USERS = {
    "caseworker_headers": build_user_headers("test-caseworker-1", "Caseworker"),
    "caseworker2_headers": build_user_headers("test-caseworker-2", "Caseworker"),
    "household_head_headers": build_user_headers("test-household-head-1", "HouseholdHead"),
    "household_head2_headers": build_user_headers("test-household-head-2", "HouseholdHead"),
    "merchant_headers": build_user_headers("test-merchant-1", "Merchant"),
    "fraud_investigator_headers": build_user_headers("test-fraud-inv-1", "FraudInvestigator"),
    "fraud_investigator2_headers": build_user_headers("test-fraud-inv-2", "FraudInvestigator"),
    "state_admin_headers": build_user_headers("test-state-admin-1", "StateAdministrator"),
    "state_admin2_headers": build_user_headers("test-state-admin-2", "StateAdministrator"),
    "system_test_headers": build_user_headers("test-system-1", "SystemTest"),
}


# Per-instance builders — mandatory for entity_backed roles
def make_household_head_headers(household_id: str) -> dict:
    """For HouseholdHead (entity_backed:Household). Pass the actual Household.id
    as X-User-ID for ownership-gated calls."""
    return build_user_headers(household_id, "HouseholdHead")


def make_merchant_headers(merchant_id: str) -> dict:
    """For Merchant (entity_backed:Merchant). Pass the actual Merchant.id
    as X-User-ID for ownership-gated calls (POST/PATCH transactions/merchants)."""
    return build_user_headers(merchant_id, "Merchant")
