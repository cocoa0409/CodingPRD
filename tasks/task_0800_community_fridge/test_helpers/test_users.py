"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed: Steward (X-User-ID = the Steward.id) and DonorAgent
(X-User-ID = the Donor.id). Ownership-gated calls MUST thread the real entity id
through the per-instance builders below; the shared TEST_USERS constants are only
safe for opaque roles or for tests that never exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles use these as their canonical form; entity-backed
# roles use them only for non-ownership tests (e.g. 401/403/404 shape checks).
TEST_USERS = {
    "network_admin_headers": build_user_headers("admin-1", "NetworkAdmin"),
    "sponsor_agent_headers": build_user_headers("sponsor-1", "SponsorAgent"),
    "member_headers": build_user_headers("member-1", "Member"),
    # entity-backed fallbacks — NOT for ownership-gated calls.
    "steward_headers": build_user_headers("steward-fallback-1", "Steward"),
    "donor_agent_headers": build_user_headers("donor-fallback-1", "DonorAgent"),
}


# Per-instance builders — required for every entity-backed role.
def make_steward_headers(user_id: str) -> dict:
    """For Steward (entity_backed:Steward). Pass the actual Steward.id whenever the
    call is ownership-gated (own shift completion, intake logged under this steward)."""
    return build_user_headers(user_id, "Steward")


def make_donor_headers(user_id: str) -> dict:
    """For DonorAgent (entity_backed:Donor). Pass the actual Donor.id whenever the
    call is ownership-gated (posting an offer under this donor's path)."""
    return build_user_headers(user_id, "DonorAgent")


def make_admin_headers() -> dict:
    return TEST_USERS["network_admin_headers"]


def make_sponsor_headers() -> dict:
    return TEST_USERS["sponsor_agent_headers"]


def make_member_headers() -> dict:
    return TEST_USERS["member_headers"]
