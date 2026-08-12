"""Pre-built role headers for every role in the PRD (§2.1).

Manager and Inspector are opaque operator identities; Homeowner,
CommitteeMember and BoardMember are backed by the Owner registry, so any
ownership-gated call MUST use the per-instance builders below with the
acting Owner's real id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    # Owner-backed roles: fallback constants for tests that do NOT exercise
    # ownership (e.g. 400/404 probes). Never use these where the call is
    # ownership-gated — X-User-ID must equal the acting Owner's id.
    "homeowner_headers": build_user_headers("test-homeowner-fallback", "Homeowner"),
    "committee_member_headers": build_user_headers("test-committee-fallback", "CommitteeMember"),
    "board_member_headers": build_user_headers("test-board-fallback", "BoardMember"),
}


def make_homeowner_headers(user_id: str) -> dict:
    """Homeowner is backed by the Owner registry: pass the acting Owner's id."""
    return build_user_headers(user_id, "Homeowner")


def make_committee_member_headers(user_id: str) -> dict:
    """CommitteeMember is backed by the Owner registry: pass the acting Owner's id."""
    return build_user_headers(user_id, "CommitteeMember")


def make_board_member_headers(user_id: str) -> dict:
    """BoardMember is backed by the Owner registry: pass the acting Owner's id."""
    return build_user_headers(user_id, "BoardMember")
