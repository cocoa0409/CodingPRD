"""Pre-built role headers for every role in the PRD.

ProgramCoordinator is an opaque identity: X-User-ID is not tied to any
persisted entity (though segregation-of-duties rules may compare the raw
identifier against a member id). LiaisonOfficer is entity-backed by
LiaisonOfficer; BlockCaptain and Member are entity-backed by Member.
Ownership-gated calls MUST use the per-instance builders with the real
entity id — never the shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque role, and for entity-backed roles
# only in tests that do not exercise ownership (wrong-role checks,
# 400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    "coordinator_headers": build_user_headers("test-coordinator-1", "ProgramCoordinator"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "officer_headers": build_user_headers("test-officer-1", "LiaisonOfficer"),
    "captain_headers": build_user_headers("test-captain-1", "BlockCaptain"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    """ProgramCoordinator (opaque identity). Pass a specific user id when a
    segregation-of-duties check must compare it against a member id."""
    return build_user_headers(user_id, "ProgramCoordinator")


def make_officer_headers(officer_id: str) -> dict:
    """For LiaisonOfficer (entity_backed:LiaisonOfficer). Pass the acting
    LiaisonOfficer.id whenever the call is ownership-gated."""
    return build_user_headers(officer_id, "LiaisonOfficer")


def make_captain_headers(member_id: str) -> dict:
    """For BlockCaptain (entity_backed:Member). Pass the acting Member.id
    whenever the call is ownership-gated."""
    return build_user_headers(member_id, "BlockCaptain")


def make_member_headers(member_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the acting Member.id whenever
    the call is ownership-gated (reporter, acknowledger, self-withdrawal)."""
    return build_user_headers(member_id, "Member")
