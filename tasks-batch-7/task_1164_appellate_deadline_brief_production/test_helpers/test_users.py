"""Pre-built role headers for the four roles in the PRD (§2.1).

CourtAdmin, CourtClerk and ParalegalStaff are opaque identities — the server
does not compare their X-User-ID to any persisted entity — so shared constants
are canonical. Attorney is entity-backed: X-User-ID must be the id of the
acting Attorney record whenever a call is ownership-gated (drafting attorney,
lead-attorney-only actions); use make_attorney_headers(attorney["id"]) there.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "court_admin_headers": build_user_headers("test-court-admin-1", "CourtAdmin"),
    "court_clerk_headers": build_user_headers("test-court-clerk-1", "CourtClerk"),
    "paralegal_headers": build_user_headers("test-paralegal-1", "ParalegalStaff"),
    # Entity-backed role: fallback ONLY for tests that never exercise
    # ownership (bad-payload 400s, 404s). Ownership-gated calls MUST use
    # make_attorney_headers(attorney["id"]).
    "attorney_headers": build_user_headers("test-attorney-1", "Attorney"),
}


def make_attorney_headers(user_id: str) -> dict:
    """For Attorney (entity-backed). Pass the actual Attorney.id as user_id
    whenever the call is ownership-gated (brief author, lead attorney)."""
    return build_user_headers(user_id, "Attorney")
