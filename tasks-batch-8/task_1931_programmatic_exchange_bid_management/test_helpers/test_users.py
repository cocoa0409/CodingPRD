"""Pre-built role headers for every role in the PRD.

ExchangeAdmin, DemandSide, and FinanceOfficer are opaque identities:
X-User-ID is not tied to any persisted entity (the FinanceOfficer id is
persisted on payout batches as created_by_user_id for the
segregation-of-duties check). PublisherManager is entity-backed by
Publisher — X-User-ID must equal the acting publisher's id on every
ownership-gated call, so fixtures MUST use make_publisher_manager_headers
with the real publisher id, never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not
# exercise ownership (400-on-bad-payload, 404-on-missing-resource, and
# wrong-role checks).
TEST_USERS = {
    "exchange_admin_headers": build_user_headers("test-admin-1", "ExchangeAdmin"),
    "demand_side_headers": build_user_headers("test-demand-1", "DemandSide"),
    "finance_officer_headers": build_user_headers("fin-1", "FinanceOfficer"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only — ownership-gated calls must use the builder below.
    "publisher_manager_headers": build_user_headers("test-pm-1", "PublisherManager"),
}


def make_exchange_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ExchangeAdmin")


def make_demand_side_headers(user_id: str = "test-demand-1") -> dict:
    return build_user_headers(user_id, "DemandSide")


def make_finance_officer_headers(user_id: str = "fin-1") -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


def make_publisher_manager_headers(publisher_id: str) -> dict:
    """For PublisherManager (entity_backed:Publisher). Pass the acting
    Publisher.id whenever the call is ownership-gated (packages, deals,
    seasonal windows, supply-chain nodes, own-scope blocklist entries)."""
    return build_user_headers(publisher_id, "PublisherManager")
