"""Pre-built role headers for every role in the PRD.

All five roles are identity-opaque (no persisted row exists for any of them),
so a shared constant is safe in every case EXCEPT guardian-scoped operations,
where X-User-ID must equal the owning student's primary_guardian_user_id.
For those, fixtures thread the guardian id chosen at student creation through
make_parent_guardian_headers(guardian_user_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "gifted_coordinator_headers": build_user_headers("test-gc-1", "GiftedCoordinator"),
    "referring_educator_headers": build_user_headers("test-edu-1", "ReferringEducator"),
    "parent_guardian_headers": build_user_headers("test-pg-1", "ParentGuardian"),
    "committee_member_headers": build_user_headers("test-cm-1", "CommitteeMember"),
    "special_ed_coordinator_headers": build_user_headers("test-se-1", "SpecialEdCoordinator"),
}


def make_gifted_coordinator_headers(user_id: str = "test-gc-1") -> dict:
    return build_user_headers(user_id, "GiftedCoordinator")


def make_referring_educator_headers(user_id: str) -> dict:
    """ReferringEducator headers bound to a specific X-User-ID. Use the same id
    at referral time and at vote time when exercising the conflict-of-interest bar."""
    return build_user_headers(user_id, "ReferringEducator")


def make_parent_guardian_headers(user_id: str) -> dict:
    """ParentGuardian headers bound to the student's primary_guardian_user_id.
    Mandatory for guardian-scoped operations (accept / decline / withdraw / appeal
    by guardian)."""
    return build_user_headers(user_id, "ParentGuardian")


def make_committee_member_headers(user_id: str) -> dict:
    """CommitteeMember headers bound to a specific X-User-ID; one vote per member
    per review, so each distinct voter needs a distinct id."""
    return build_user_headers(user_id, "CommitteeMember")


def make_special_ed_coordinator_headers(user_id: str = "test-se-1") -> dict:
    return build_user_headers(user_id, "SpecialEdCoordinator")
