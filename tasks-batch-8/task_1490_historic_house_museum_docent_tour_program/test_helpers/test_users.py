"""Pre-built role headers for every role in the PRD.

Per PRD section 2.1: MuseumAdmin / Curator / DocentCoordinator /
FrontDeskStaff use opaque operator identifiers; Docent and Member are
entity-backed — X-User-ID must equal the acting Docent / Member id, so
ownership-gated calls must use make_docent_headers(entity_id) /
make_member_headers(entity_id) with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. For entity-backed roles (Docent, Member) these are fallbacks for
# non-ownership contexts only; ownership-gated calls MUST use the builders.
TEST_USERS = {
    "museum_admin_headers": build_user_headers("test-museum-admin-1", "MuseumAdmin"),
    "curator_headers": build_user_headers("test-curator-1", "Curator"),
    "docent_coordinator_headers": build_user_headers(
        "test-docent-coordinator-1", "DocentCoordinator"),
    "front_desk_staff_headers": build_user_headers(
        "test-front-desk-1", "FrontDeskStaff"),
    # entity_backed: shared constants only for non-ownership contexts.
    "docent_headers": build_user_headers("test-docent-1", "Docent"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_docent_headers(user_id: str) -> dict:
    """For the Docent role (entity-backed). Pass the actual Docent.id as
    user_id whenever the call is ownership-gated (shift confirm/decline)."""
    return build_user_headers(user_id, "Docent")


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity-backed). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (own bookings / surveys)."""
    return build_user_headers(user_id, "Member")


def make_headers_without_user_id(role: str) -> dict:
    """Headers with X-User-Role present but X-User-ID omitted, for the
    ERR_UNAUTHENTICATED path of PRD section 2.1."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
