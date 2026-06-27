"""Pre-built role headers for every role in the PRD (§2.1).

The four roles are SchoolCoordinator, StudioPhotographer, FulfillmentClerk
(all three opaque operators whose X-User-ID is never compared to any stored row)
and Guardian, whose identity is entity-backed by a student: a guardian's
X-User-ID is the opaque guardian_user_id recorded on the students they own, and
ownership checks compare a target student's guardian_user_id to that value.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants. The three operator roles are opaque, so their shared
# constants are the canonical form. The Guardian shared constant is a fallback
# usable only for tests that do not exercise student ownership.
TEST_USERS = {
    "coordinator_headers": build_user_headers("test-coordinator-1", "SchoolCoordinator"),
    "photographer_headers": build_user_headers("test-photographer-1", "StudioPhotographer"),
    "clerk_headers": build_user_headers("test-clerk-1", "FulfillmentClerk"),
    # Guardian fallback (non-ownership tests only). Ownership-gated calls MUST use
    # make_guardian_headers(<the student's guardian_user_id>).
    "guardian_headers": build_user_headers("test-guardian-1", "Guardian"),
}


def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    """SchoolCoordinator is opaque; X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "SchoolCoordinator")


def make_photographer_headers(user_id: str = "test-photographer-1") -> dict:
    """StudioPhotographer is opaque; X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "StudioPhotographer")


def make_clerk_headers(user_id: str = "test-clerk-1") -> dict:
    """FulfillmentClerk is opaque; X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "FulfillmentClerk")


def make_guardian_headers(guardian_user_id: str) -> dict:
    """For Guardian (entity-backed by a student). Pass the guardian_user_id that
    was recorded on the target student whenever the call is ownership-gated
    (creating/submitting/cancelling/reading that student's orders)."""
    return build_user_headers(guardian_user_id, "Guardian")
