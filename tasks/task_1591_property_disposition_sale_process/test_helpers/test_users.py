"""Pre-built role headers for every role in the PRD.

Buyer is entity-backed: its X-User-ID must be the id of the acting Bidder
(PRD User and Role-Based Access Control), so ownership-gated calls must use
make_buyer_headers(<real Bidder id>). The shared TEST_USERS entry for Buyer
is a fallback for tests that never exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "dm_headers": build_user_headers("dm-1", "DispositionManager"),
    "analyst_headers": build_user_headers("analyst-1", "AssetAnalyst"),
    "ic_headers": build_user_headers("ic-1", "InvestmentCommittee"),
    "broker_headers": build_user_headers("broker-1", "Broker"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
    "co_headers": build_user_headers("co-1", "ClosingOfficer"),
    "ls_headers": build_user_headers("ls-1", "LoanServicer"),
}


def make_dm_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DispositionManager")


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AssetAnalyst")


def make_ic_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InvestmentCommittee")


def make_broker_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Broker")


def make_buyer_headers(user_id: str) -> dict:
    """Buyer is entity-backed by Bidder: pass the real Bidder.id whenever the
    call is ownership-gated (bids, dd-items, statement disputes, claims,
    buyer termination)."""
    return build_user_headers(user_id, "Buyer")


def make_co_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClosingOfficer")


def make_ls_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LoanServicer")
