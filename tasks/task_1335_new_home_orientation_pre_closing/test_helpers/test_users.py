"""Pre-built role headers for every role in the PRD (§2.1).

Shared constants in TEST_USERS are safe for the opaque manager role and for
tests that never exercise entity-backed ownership. For the entity-backed
roles (CustomerCareRep, Homebuyer) always prefer the per-instance builders
with the real entity id whenever the call is ownership- or segregation-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: X-User-ID is never compared to a persisted entity id.
    "manager_headers": build_user_headers("test-manager-1", "CustomerCareManager"),
    # Entity-backed fallbacks — non-ownership reads / negative tests only.
    "rep_headers": build_user_headers("test-rep-1", "CustomerCareRep"),
    "buyer_headers": build_user_headers("test-buyer-1", "Homebuyer"),
}


def make_rep_headers(rep_id: str) -> dict:
    """Headers for a CustomerCareRep caller. Pass the actual CustomerCareRep.id
    whenever the call is ownership- or segregation-gated (e.g. conducting an
    appointment, verifying attendees of someone else's appointment)."""
    return build_user_headers(rep_id, "CustomerCareRep")


def make_buyer_headers(buyer_id: str) -> dict:
    """Headers for a Homebuyer caller. Pass the actual Homebuyer.id whenever
    the call is buyer-scoped (withdraw, sign-off, respond, survey submit)."""
    return build_user_headers(buyer_id, "Homebuyer")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    """Headers for a CustomerCareManager caller (opaque identity)."""
    return build_user_headers(user_id, "CustomerCareManager")
