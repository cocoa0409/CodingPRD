"""Pre-built role headers for every role in the PRD (§2.1).

BoxOfficeAgent and FinanceClerk carry opaque X-User-ID values not tied to any
entity, so their shared constants are canonical. AccountHolder's X-User-ID is
the id of the acting Account (§2.1): ownership checks compare a resource's
owning-account FK to X-User-ID. Therefore ownership-gated AccountHolder calls
MUST use make_account_holder_headers(account_id) with the real Account id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "box_office_headers": build_user_headers("agent-box-office-1", "BoxOfficeAgent"),
    "finance_headers": build_user_headers("clerk-finance-1", "FinanceClerk"),
    # entity_backed:Account — fallback for non-ownership tests only (e.g. a
    # holder hitting a shared read or a 404; never for ownership-gated writes).
    "account_holder_headers": build_user_headers("holder-fallback-1", "AccountHolder"),
}


def make_account_holder_headers(account_id: str) -> dict:
    """Headers for an AccountHolder acting as the Account whose id is account_id.

    Pass the real Account.id whenever the call is ownership-gated (creating /
    forwarding / listing / cancelling transfers, accepting a renewal, or adding
    parking on the holder's own subscription)."""
    return build_user_headers(account_id, "AccountHolder")


def make_box_office_headers(user_id: str = "agent-box-office-1") -> dict:
    return build_user_headers(user_id, "BoxOfficeAgent")


def make_finance_headers(user_id: str = "clerk-finance-1") -> dict:
    return build_user_headers(user_id, "FinanceClerk")
