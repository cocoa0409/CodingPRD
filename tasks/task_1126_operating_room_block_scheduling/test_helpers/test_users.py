"""Pre-built role headers for every role in the PRD (§2.1).

Surgeon is entity-backed: X-User-ID must be the acting Surgeon's id whenever
the call is ownership-gated. Always use make_surgeon_headers(surgeon["id"])
for those calls; the shared constant below is only for negative/RBAC tests
where no real surgeon identity is required.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are canonical.
    "admin_headers": build_user_headers("test-admin-1", "SchedulingAdmin"),
    "nurse_headers": build_user_headers("test-nurse-1", "CirculatorNurse"),
    "coordinator_headers": build_user_headers("test-anes-1", "AnesthesiaCoordinator"),
    "chair_headers": build_user_headers("test-chair-1", "BlockCommitteeChair"),
    "member_headers": build_user_headers("cm_1", "CommitteeMember"),
    # Entity-backed role: fallback for non-ownership tests ONLY (e.g. RBAC
    # denials). Never use for ownership-gated calls — use make_surgeon_headers.
    "surgeon_headers": build_user_headers("test-surgeon-1", "Surgeon"),
}


def make_surgeon_headers(user_id: str) -> dict:
    """Surgeon is entity-backed: pass the acting Surgeon's id for any
    ownership-gated call (posting/scheduling/cancelling cases, releasing own
    blocks, filing/withdrawing reallocation requests)."""
    return build_user_headers(user_id, "Surgeon")


def make_committee_member_headers(user_id: str) -> dict:
    """CommitteeMember is opaque but recorded as member_ref on each vote;
    distinct members need distinct user ids."""
    return build_user_headers(user_id, "CommitteeMember")
