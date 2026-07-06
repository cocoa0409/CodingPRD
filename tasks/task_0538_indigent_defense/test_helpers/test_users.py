"""Pre-built role headers for every role in the PRD.

Four roles carry an opaque X-User-ID (IntakeClerk, ScreeningOfficer,
AssignmentCoordinator, SupervisingAttorney); the shared constant is the
canonical form for those. The Attorney role is entity-backed: its X-User-ID
must equal the acting Attorney entity's id, so ownership-gated calls MUST use
make_attorney_headers(attorney_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "intake_clerk_headers": build_user_headers("clerk-1", "IntakeClerk"),
    "screening_officer_headers": build_user_headers("officer-1", "ScreeningOfficer"),
    "assignment_coordinator_headers": build_user_headers("coord-1", "AssignmentCoordinator"),
    "supervising_attorney_headers": build_user_headers("super-1", "SupervisingAttorney"),
    # Fallback only — Attorney is entity_backed; ownership-gated calls must use
    # make_attorney_headers(attorney_id) with the real attorney id.
    "attorney_headers": build_user_headers("attorney-1", "Attorney"),
}


def make_intake_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeClerk")


def make_screening_officer_headers(user_id: str) -> dict:
    """ScreeningOfficer is opaque; a distinct user_id is used to exercise
    segregation-of-duties, where decided_by_user_id is recorded."""
    return build_user_headers(user_id, "ScreeningOfficer")


def make_assignment_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AssignmentCoordinator")


def make_supervising_attorney_headers(user_id: str) -> dict:
    """SupervisingAttorney is opaque; a distinct user_id is used to exercise
    segregation-of-duties on recoupment waiver (waived_by_user_id)."""
    return build_user_headers(user_id, "SupervisingAttorney")


def make_attorney_headers(user_id: str) -> dict:
    """For the Attorney role (entity_backed:Attorney). Pass the actual
    Attorney.id as user_id whenever the call is ownership-gated (create /
    submit / revise voucher)."""
    return build_user_headers(user_id, "Attorney")
