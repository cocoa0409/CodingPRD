"""Pre-built role headers for every role in the PRD (§2.1).

AccountHolder is entity-backed on Account: ownership-gated calls MUST use
make_account_holder_headers(account["id"]) so X-User-ID equals the account id.
The shared constant is a fallback only for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "desk_admin_headers": build_user_headers("desk-admin-1", "DeskAdministrator"),
    "vendor_feed_headers": build_user_headers("vendor-feed-1", "VendorFeed"),
    "analyst_1_headers": build_user_headers("analyst-1", "EventAnalyst"),
    "analyst_2_headers": build_user_headers("analyst-2", "EventAnalyst"),
    "ops_headers": build_user_headers("ops-1", "OperationsManager"),
    "examiner_1_headers": build_user_headers("examiner-1", "ClaimsExaminer"),
    "custodian_feed_headers": build_user_headers("custodian-feed-1", "CustodianFeed"),
    # Fallback for non-ownership tests only (PRD §2.1: entity-backed role).
    "account_holder_headers": build_user_headers("holder-opaque-1", "AccountHolder"),
}


def make_account_holder_headers(account_id: str) -> dict:
    """For AccountHolder (entity-backed on Account). Pass the actual Account.id
    whenever the call is ownership-gated (election submit/withdraw/resubmit,
    claim file)."""
    return build_user_headers(account_id, "AccountHolder")


def make_analyst_headers(user_id: str) -> dict:
    """Per-analyst headers; segregation-of-duties compares X-User-ID."""
    return build_user_headers(user_id, "EventAnalyst")


def make_examiner_headers(user_id: str) -> dict:
    """Per-examiner headers; segregation-of-duties compares X-User-ID."""
    return build_user_headers(user_id, "ClaimsExaminer")
