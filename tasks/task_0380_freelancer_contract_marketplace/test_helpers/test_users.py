"""Pre-built role headers for every role in the PRD (§2.1).

Client and Freelancer are entity-backed roles: their X-User-ID must equal the id of
the acting entity for ownership-gated calls. For those calls always use the
make_*_headers(entity_id) builders. The shared TEST_USERS constants are only safe for
calls that do not exercise ownership (e.g. 400-on-bad-payload, 404-on-missing-resource)
or for the opaque operator roles (Arbitrator, PlatformAdmin).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and non-ownership tests only.
TEST_USERS = {
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "client_headers": build_user_headers("test-client-1", "Client"),
    "freelancer_headers": build_user_headers("test-freelancer-1", "Freelancer"),
    # opaque roles: shared constant is the canonical form.
    "arbitrator_headers": build_user_headers("test-arbitrator-1", "Arbitrator"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


# Per-instance builders — required for every entity_backed role.
def make_client_headers(client_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id whenever the call
    is ownership-gated (job postings, contracts, milestone funding/approval/release, etc.)."""
    return build_user_headers(client_id, "Client")


def make_freelancer_headers(freelancer_id: str) -> dict:
    """For Freelancer (entity_backed:Freelancer). Pass the actual Freelancer.id whenever
    the call is ownership-gated (proposal submit/withdraw, profile patch, submit-work, timelogs)."""
    return build_user_headers(freelancer_id, "Freelancer")


def make_arbitrator_headers(user_id: str = "test-arbitrator-1") -> dict:
    """For Arbitrator (opaque). Identifier is recorded but never compared to an entity id."""
    return build_user_headers(user_id, "Arbitrator")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For PlatformAdmin (opaque). Identifier is recorded but never compared to an entity id."""
    return build_user_headers(user_id, "PlatformAdmin")
