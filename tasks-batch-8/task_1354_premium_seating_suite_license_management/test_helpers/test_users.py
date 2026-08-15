"""Pre-built role headers for every role in the PRD (§2.1).

AccountHolder is entity-backed by Account: any ownership-gated call must use
make_account_holder_headers(account_id) with the real Account.id. The shared
constant is only for tests that never exercise ownership (e.g. role-denied calls).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("ops-admin-1", "StadiumAdmin"),
    "rep_headers": build_user_headers("sales-rep-1", "PremiumSalesRep"),
    "finance_headers": build_user_headers("finance-1", "FinanceController"),
    "event_services_headers": build_user_headers("event-svc-1", "EventServicesManager"),
    # Fallback for non-ownership contexts only (e.g. ERR_FORBIDDEN_FOR_ROLE checks).
    "holder_headers": build_user_headers("holder-generic", "AccountHolder"),
}


def make_account_holder_headers(account_id: str) -> dict:
    """AccountHolder identity is the Account.id (PRD §2.1). Pass the real account id
    whenever the call is ownership-gated (execute, own payments, own catering, ...)."""
    return build_user_headers(account_id, "AccountHolder")


def anonymous_headers() -> dict:
    """No user-context headers at all."""
    return {}
