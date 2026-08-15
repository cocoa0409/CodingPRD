"""Pre-built role headers for every role in the PRD.

All five roles have opaque identities: X-User-ID is not tied to any persisted
entity, so the shared constants below are the canonical form for every call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "broker_principal_headers": build_user_headers("test-principal-1", "BrokerPrincipal"),
    "listing_agent_headers": build_user_headers("test-listing-agent-1", "ListingAgent"),
    "buyer_agent_headers": build_user_headers("test-buyer-agent-1", "BuyerAgent"),
    "escrow_officer_headers": build_user_headers("test-escrow-1", "EscrowOfficer"),
    "facility_scheduler_headers": build_user_headers("test-scheduler-1", "FacilityScheduler"),
}


def make_broker_principal_headers(user_id: str = "test-principal-1") -> dict:
    return build_user_headers(user_id, "BrokerPrincipal")


def make_listing_agent_headers(user_id: str = "test-listing-agent-1") -> dict:
    return build_user_headers(user_id, "ListingAgent")


def make_buyer_agent_headers(user_id: str = "test-buyer-agent-1") -> dict:
    return build_user_headers(user_id, "BuyerAgent")


def make_escrow_officer_headers(user_id: str = "test-escrow-1") -> dict:
    return build_user_headers(user_id, "EscrowOfficer")


def make_facility_scheduler_headers(user_id: str = "test-scheduler-1") -> dict:
    return build_user_headers(user_id, "FacilityScheduler")
