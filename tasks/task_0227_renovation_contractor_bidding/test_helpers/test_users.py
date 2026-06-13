"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed (Homeowner, Contractor): their X-User-ID must equal
the id of the acting persisted record for ownership checks to pass. For those
roles use the make_*_headers(user_id) builders, threading the real entity id.

Three roles are opaque (EscrowAgent, PlatformAdmin, Anonymous): the X-User-ID is
an operator identifier never compared to any record's id, so the shared constant
is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Entity-backed roles: shared constant is a fallback for non-ownership tests
    # (e.g. 401/403/404 cases). Ownership-gated calls MUST use the builders below.
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
    # Opaque roles: shared constant is the canonical form.
    "escrow_agent_headers": build_user_headers("test-escrow-1", "EscrowAgent"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


def make_homeowner_headers(user_id: str) -> dict:
    """For Homeowner (entity_backed:Homeowner). Pass the acting Homeowner.id as
    user_id whenever the call is ownership-gated (project sub-resources)."""
    return build_user_headers(user_id, "Homeowner")


def make_contractor_headers(user_id: str) -> dict:
    """For Contractor (entity_backed:Contractor). Pass the acting Contractor.id as
    user_id whenever the call is ownership-gated (bids, draw requests)."""
    return build_user_headers(user_id, "Contractor")
