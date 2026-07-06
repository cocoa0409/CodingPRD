"""Pre-built role headers for every role in the PRD.

Five roles carry an opaque identity (ProgramAdmin, RightOfWayAgent, Appraiser,
EscrowOfficer, UtilityCoordinator): their X-User-ID is never compared to any
entity id, so the shared constant is the canonical form.

PropertyOwner is entity-backed by an OwnershipInterest: its X-User-ID must equal
the acting OwnershipInterest.id. Ownership-gated calls MUST use
make_property_owner_headers(ownership_interest_id); the shared constant is only a
fallback for tests that never exercise the ownership check.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "right_of_way_agent_headers": build_user_headers("agent-1", "RightOfWayAgent"),
    "appraiser_headers": build_user_headers("appraiser-1", "Appraiser"),
    "escrow_officer_headers": build_user_headers("escrow-1", "EscrowOfficer"),
    "utility_coordinator_headers": build_user_headers("utility-1", "UtilityCoordinator"),
    # Fallback only — non-ownership tests. Real owner calls use the builder below.
    "property_owner_headers": build_user_headers("owner-fallback", "PropertyOwner"),
}

# Headers with no X-User-Role — for the unauthenticated case.
ANON_HEADERS = {"X-User-ID": "anon-1"}


def make_property_owner_headers(ownership_interest_id: str) -> dict:
    """For PropertyOwner (entity_backed:OwnershipInterest). Pass the acting
    OwnershipInterest.id whenever the call is ownership-gated."""
    return build_user_headers(ownership_interest_id, "PropertyOwner")
