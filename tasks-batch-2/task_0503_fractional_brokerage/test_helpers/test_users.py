"""Pre-built role headers for every role in the PRD.

The PRD declares exactly four roles. AccountHolder is entity-backed: its
X-User-ID must equal the acting Account's id for ownership-gated calls, so a
per-instance builder make_account_holder_headers(account_id) is mandatory.
The other three roles (ComplianceOfficer, ClearingSystem, MarketData) are
opaque operator identities whose X-User-ID is recorded but never matched to
an entity id, so a shared constant is the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for AccountHolder tests that
# do NOT exercise ownership (e.g. 401/missing-role, or never-owned resources).
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "account_holder_headers": build_user_headers("test-account-holder-1", "AccountHolder"),
    # opaque roles: shared constant is the canonical form.
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "clearing_system_headers": build_user_headers("test-clearing-1", "ClearingSystem"),
    "market_data_headers": build_user_headers("test-market-data-1", "MarketData"),
}


# Per-instance builder — required for the entity_backed AccountHolder role.
def make_account_holder_headers(account_id: str) -> dict:
    """For AccountHolder (entity_backed:Account). Pass the actual Account.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(account_id, "AccountHolder")


def make_compliance_officer_headers(user_id: str = "test-compliance-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_clearing_system_headers(user_id: str = "test-clearing-1") -> dict:
    return build_user_headers(user_id, "ClearingSystem")


def make_market_data_headers(user_id: str = "test-market-data-1") -> dict:
    return build_user_headers(user_id, "MarketData")
