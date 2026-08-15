"""Pre-built role headers for every role in the PRD (§2.1).

BidCoordinator is entity-backed: when X-User-Role is BidCoordinator, X-User-ID
is the id of the acting Broadcaster. Ownership-gated calls MUST use
make_bid_coordinator_headers(<broadcaster id>); the shared
TEST_USERS["bid_coordinator_headers"] constant is only for tests that do not
exercise ownership (e.g. 400/403/404 probes).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "rights_manager_headers": build_user_headers("test-rm-1", "RightsManager"),
    # Fallback for non-ownership probes only — see module docstring.
    "bid_coordinator_headers": build_user_headers("test-bc-1", "BidCoordinator"),
    "finance_controller_headers": build_user_headers("test-fc-1", "FinanceController"),
    "production_auditor_headers": build_user_headers("test-pa-1", "ProductionAuditor"),
    "compliance_officer_headers": build_user_headers("test-co-1", "ComplianceOfficer"),
}


def make_bid_coordinator_headers(broadcaster_id: str) -> dict:
    """BidCoordinator headers bound to a real Broadcaster id (entity-backed role).

    Pass the actual Broadcaster.id whenever the call is ownership-gated
    (filing/submitting/withdrawing bids, sublicense requests, renewal offers,
    measurement disputes).
    """
    return build_user_headers(broadcaster_id, "BidCoordinator")
