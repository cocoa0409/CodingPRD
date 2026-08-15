"""Pre-built role headers for every role in the PRD.

FirmAdmin and Auditor are opaque identities: X-User-ID is not tied to any
persisted entity. Agent, BusinessManager, and Publicist are entity-backed by
TeamMember (X-User-ID is the acting TeamMember's id); Artist is entity-backed
by Artist (X-User-ID is the artist's id). Ownership-gated calls MUST use the
per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "firm_admin_headers": build_user_headers("test-firm-admin-1", "FirmAdmin"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
    "business_manager_headers": build_user_headers("test-bm-1", "BusinessManager"),
    "publicist_headers": build_user_headers("test-publicist-1", "Publicist"),
    "artist_headers": build_user_headers("test-artist-1", "Artist"),
}


def make_firm_admin_headers(user_id: str = "test-firm-admin-1") -> dict:
    return build_user_headers(user_id, "FirmAdmin")


def make_auditor_headers(user_id: str = "test-auditor-1") -> dict:
    return build_user_headers(user_id, "Auditor")


def make_agent_headers(team_member_id: str) -> dict:
    """For Agent (entity_backed:TeamMember). Pass the acting TeamMember.id
    whenever the call is ownership-gated."""
    return build_user_headers(team_member_id, "Agent")


def make_business_manager_headers(team_member_id: str) -> dict:
    """For BusinessManager (entity_backed:TeamMember). Pass the acting
    TeamMember.id whenever the call is ownership-gated."""
    return build_user_headers(team_member_id, "BusinessManager")


def make_publicist_headers(team_member_id: str) -> dict:
    """For Publicist (entity_backed:TeamMember). Pass the acting TeamMember.id
    whenever the call is ownership-gated."""
    return build_user_headers(team_member_id, "Publicist")


def make_artist_headers(artist_id: str) -> dict:
    """For Artist (entity_backed:Artist). Pass the acting Artist.id whenever
    the call is ownership-gated."""
    return build_user_headers(artist_id, "Artist")
