"""Pre-built role headers for every role in the PRD (§2.1).

Manager and FrontDesk are opaque operator identifiers — the server records but
does not match X-User-ID against any entity, so shared constants are the
canonical form. Flyer and Instructor are entity-backed: ownership checks
compare X-User-ID to the resource's member_id / instructor_id, so any call that
is ownership-gated MUST use the per-instance builder with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constant is canonical.
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    "frontdesk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
    # Entity-backed roles — shared constant is a fallback for non-ownership
    # tests only (e.g. a 403 that fires before any ownership comparison).
    "flyer_headers": build_user_headers("test-flyer-1", "Flyer"),
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
}


def make_flyer_headers(member_id: str) -> dict:
    """For Flyer (entity-backed:Member). Pass the acting Member.id as X-User-ID
    whenever the call is ownership-gated."""
    return build_user_headers(member_id, "Flyer")


def make_instructor_headers(instructor_id: str) -> dict:
    """For Instructor (entity-backed:Instructor). Pass the acting Instructor.id
    as X-User-ID; instructor-exclusive flight actions (complete/abort) and
    session-running actions compare the session's instructor_id to X-User-ID."""
    return build_user_headers(instructor_id, "Instructor")
