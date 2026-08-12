"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (FairBoardAdmin, WeighMaster, ShowClerk, Auctioneer,
HealthInspector, Treasurer) carry operator identifiers never compared to an
entity id, so shared constants are safe for them. Entity-backed roles
(Exhibitor, Judge, Buyer) MUST use the per-instance builders with the actual
entity id whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin": build_user_headers("admin-1", "FairBoardAdmin"),
    "admin_a": build_user_headers("admin-a", "FairBoardAdmin"),
    "admin_b": build_user_headers("admin-b", "FairBoardAdmin"),
    "weigh_master": build_user_headers("weigh-1", "WeighMaster"),
    "show_clerk": build_user_headers("clerk-1", "ShowClerk"),
    "auctioneer": build_user_headers("auction-1", "Auctioneer"),
    "health_inspector": build_user_headers("vet-1", "HealthInspector"),
    "treasurer": build_user_headers("treas-1", "Treasurer"),
    "treasurer_1": build_user_headers("treas-1", "Treasurer"),
    "treasurer_2": build_user_headers("treas-2", "Treasurer"),
}


def make_admin_headers(user_id: str) -> dict:
    """FairBoardAdmin is opaque; distinct ids matter for maker-checker rules."""
    return build_user_headers(user_id, "FairBoardAdmin")


def make_treasurer_headers(user_id: str) -> dict:
    """Treasurer is opaque; distinct ids matter for approve/pay segregation."""
    return build_user_headers(user_id, "Treasurer")


def make_exhibitor_headers(exhibitor_id: str) -> dict:
    """Exhibitor is entity-backed: X-User-ID must be the Exhibitor record id."""
    return build_user_headers(exhibitor_id, "Exhibitor")


def make_judge_headers(judge_id: str) -> dict:
    """Judge is entity-backed: X-User-ID must be the Judge record id."""
    return build_user_headers(judge_id, "Judge")


def make_buyer_headers(buyer_id: str) -> dict:
    """Buyer is entity-backed: X-User-ID must be the Buyer record id."""
    return build_user_headers(buyer_id, "Buyer")
