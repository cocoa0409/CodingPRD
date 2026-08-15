"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (GovernanceAdmin, ComplianceOfficer, ExecutiveDirector) use shared
constants. Entity-backed roles (BoardChair, BoardDirector, Treasurer) MUST be
built per member via the make_*_headers builders so X-User-ID equals the id of
an ACTIVE BoardMember of the nonprofit being acted on.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership-gated calls.
TEST_USERS = {
    "governance_admin_headers": build_user_headers("test-admin-1", "GovernanceAdmin"),
    "compliance_officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
    "executive_director_headers": build_user_headers("test-exec-1", "ExecutiveDirector"),
    # Fallbacks for non-ownership-gated calls only (e.g., 404/400 probes).
    "board_chair_headers": build_user_headers("test-chair-1", "BoardChair"),
    "board_director_headers": build_user_headers("test-director-1", "BoardDirector"),
    "treasurer_headers": build_user_headers("test-treasurer-1", "Treasurer"),
}


def make_board_chair_headers(user_id: str) -> dict:
    """BoardChair is entity-backed: pass an ACTIVE BoardMember id with officer_role CHAIR."""
    return build_user_headers(user_id, "BoardChair")


def make_board_director_headers(user_id: str) -> dict:
    """BoardDirector is entity-backed: pass an ACTIVE BoardMember id."""
    return build_user_headers(user_id, "BoardDirector")


def make_treasurer_headers(user_id: str) -> dict:
    """Treasurer is entity-backed: pass an ACTIVE BoardMember id with officer_role TREASURER."""
    return build_user_headers(user_id, "Treasurer")


def headers_for_member(member: dict) -> dict:
    """Role headers for an entity-backed caller, derived from the member's officer_role."""
    role = member.get("officer_role", "NONE")
    if role == "CHAIR":
        return make_board_chair_headers(member["id"])
    if role == "TREASURER":
        return make_treasurer_headers(member["id"])
    return make_board_director_headers(member["id"])
