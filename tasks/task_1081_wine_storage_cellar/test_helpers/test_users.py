"""Pre-built role headers for every role in the Wine-Storage Cellar PRD.

CellarMember is the only entity-backed role: X-User-ID must equal the acting
Member's id for ownership-gated calls. Every ownership-gated fixture/test MUST use
make_cellar_member_headers(member_id) with the real member id, not the shared
constant below (the shared constant is a fallback for non-ownership tests only).

The other four roles are opaque. For Appraiser, X-User-ID is recorded as
created_by_user_id and later compared for segregation of duties, so create and
finalize must use two distinct appraiser identities.
"""
from prd_bench_local_runner.testing import build_user_headers
from .constants import APPRAISER_ALPHA, APPRAISER_BETA

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "cellar_manager_headers": build_user_headers("mgr-1", "CellarManager"),
    "cellar_member_headers": build_user_headers("member-generic", "CellarMember"),
    "appraiser_headers": build_user_headers(APPRAISER_ALPHA, "Appraiser"),
    "appraiser_alpha_headers": build_user_headers(APPRAISER_ALPHA, "Appraiser"),
    "appraiser_beta_headers": build_user_headers(APPRAISER_BETA, "Appraiser"),
    "insurance_agent_headers": build_user_headers("agent-1", "InsuranceAgent"),
    "auction_broker_headers": build_user_headers("broker-1", "AuctionBroker"),
}


def make_cellar_member_headers(member_id: str) -> dict:
    """For CellarMember (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (bottles, movement requests, consignments,
    waitlist entries, insurance reads of own resources)."""
    return build_user_headers(member_id, "CellarMember")


def make_appraiser_headers(user_id: str) -> dict:
    """For Appraiser (opaque, but X-User-ID drives segregation of duties). Pass a
    distinct identity for the finalizer than for the creator."""
    return build_user_headers(user_id, "Appraiser")
