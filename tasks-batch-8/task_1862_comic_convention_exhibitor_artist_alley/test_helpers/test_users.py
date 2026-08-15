"""Pre-built role headers for every role in the PRD (Section 2.1).

The Exhibitor role is entity-backed: its X-User-ID must be the Exhibitor's id
returned by self-registration. Use make_exhibitor_headers(exhibitor_id) for any
ownership-gated call. The other roles carry opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (400/404 checks, operator-role actions).
TEST_USERS = {
    "director_headers": build_user_headers("dir-1", "ShowDirector"),
    "director2_headers": build_user_headers("dir-2", "ShowDirector"),
    "ops_headers": build_user_headers("ops-1", "OperationsStaff"),
    "ops2_headers": build_user_headers("ops-2", "OperationsStaff"),
    "juror_1_headers": build_user_headers("juror-1", "JuryMember"),
    "juror_2_headers": build_user_headers("juror-2", "JuryMember"),
    "juror_3_headers": build_user_headers("juror-3", "JuryMember"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # Fallback only for non-ownership Exhibitor calls (e.g. public list reads).
    "exhibitor_headers": build_user_headers(
        "00000000-0000-0000-0000-000000000000", "Exhibitor"
    ),
}


def make_director_headers(user_id: str = "dir-1") -> dict:
    """ShowDirector (opaque operator id)."""
    return build_user_headers(user_id, "ShowDirector")


def make_ops_headers(user_id: str = "ops-1") -> dict:
    """OperationsStaff (opaque operator id)."""
    return build_user_headers(user_id, "OperationsStaff")


def make_juror_headers(user_id: str) -> dict:
    """JuryMember (opaque juror id, recorded as juror_user_id)."""
    return build_user_headers(user_id, "JuryMember")


def make_exhibitor_headers(user_id: str) -> dict:
    """Exhibitor (entity-backed). Pass the actual Exhibitor.id whenever the
    call is ownership-gated."""
    return build_user_headers(user_id, "Exhibitor")


def make_anonymous_headers(user_id: str = "anon-1") -> dict:
    """Anonymous (unregistered; only exhibitor self-registration is open)."""
    return build_user_headers(user_id, "Anonymous")
