"""Pre-built role headers for every role in the PRD (§2.1).

Identity model: Reviewer is entity-backed — its X-User-ID must be the id of the
acting Reviewer entity, so ownership-gated reviewer calls must use
make_reviewer_headers(reviewer["id"]). All other roles carry opaque identifiers;
their per-instance makers exist so tests can control the opaque user id (e.g.,
segregation-of-duties scenarios where two roles share one X-User-ID).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not depend on
# the caller's identity matching a specific stored user id.
TEST_USERS = {
    "officer_headers": build_user_headers("test-officer-1", "AccreditationOfficer"),
    "commission_headers": build_user_headers("test-commission-1", "AccreditationCommission"),
    "leader_headers": build_user_headers("test-leader-1", "SchoolLeader"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "reviewer_headers": build_user_headers("test-reviewer-1", "Reviewer"),
    "bursar_headers": build_user_headers("test-bursar-1", "SystemBursar"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
}


def make_officer_headers(user_id: str) -> dict:
    """AccreditationOfficer with a chosen opaque X-User-ID (e.g., to collide with
    an evidence item's submitted_by_user_id in segregation-of-duties tests)."""
    return build_user_headers(user_id, "AccreditationOfficer")


def make_commission_headers(user_id: str = "test-commission-1") -> dict:
    return build_user_headers(user_id, "AccreditationCommission")


def make_leader_headers(user_id: str) -> dict:
    """SchoolLeader with a chosen opaque X-User-ID; recorded as
    submitted_by_user_id on evidence items the leader submits."""
    return build_user_headers(user_id, "SchoolLeader")


def make_reviewer_headers(reviewer_id: str) -> dict:
    """For Reviewer (entity_backed:Reviewer). Pass the actual Reviewer.id
    whenever the call is identity-gated (findings, issue-report, verify)."""
    return build_user_headers(reviewer_id, "Reviewer")


def make_bursar_headers(user_id: str = "test-bursar-1") -> dict:
    return build_user_headers(user_id, "SystemBursar")


def make_anonymous_headers(user_id: str = "test-anonymous-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
