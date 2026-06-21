"""Pre-built role headers for every role in the PRD (§2.1).

Per §2.1: when X-User-Role is Applicant, X-User-ID is the id of the acting Applicant
and ownership checks compare a resource's applicant foreign key to X-User-ID. The
LicenseAgent, DrawOfficer, and GameWarden roles carry an opaque operator identifier
not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - DrawOfficer / LicenseAgent / GameWarden are opaque: the shared constant is canonical.
#   - Applicant is entity_backed: the shared constant is a fallback for tests that do NOT
#     exercise ownership (e.g. 400-on-bad-payload, 404-on-missing-resource). For any
#     ownership-gated Applicant call, use make_applicant_headers(applicant_id) instead.
TEST_USERS = {
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "license_agent_headers": build_user_headers("test-agent-1", "LicenseAgent"),
    "draw_officer_headers": build_user_headers("test-officer-1", "DrawOfficer"),
    "game_warden_headers": build_user_headers("test-warden-1", "GameWarden"),
}


def make_applicant_headers(applicant_id: str) -> dict:
    """For the Applicant role (entity_backed:Applicant). Pass the actual Applicant.id as
    X-User-ID whenever the call is ownership-gated (own draw application, own harvest, etc.)."""
    return build_user_headers(applicant_id, "Applicant")
