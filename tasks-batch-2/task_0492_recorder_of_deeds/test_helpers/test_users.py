"""Pre-built role headers for every role in the PRD.

Roles: Submitter (entity_backed:Submitter), Examiner / Recorder / Clerk (opaque).
For Submitter, ownership-gated calls must use make_submitter_headers(<submitter.id>);
the shared TEST_USERS constant is a fallback for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "submitter_headers": build_user_headers("test-submitter-1", "Submitter"),
    # opaque roles: shared constant is the canonical form.
    "examiner_headers": build_user_headers("ex-1", "Examiner"),
    "recorder_headers": build_user_headers("rec-1", "Recorder"),
    "clerk_headers": build_user_headers("clerk-1", "Clerk"),
}


# --- Per-instance builder for the only entity_backed role ---
def make_submitter_headers(user_id: str) -> dict:
    """For Submitter (entity_backed:Submitter). Pass the actual Submitter.id as
    user_id whenever the call is ownership-gated (submit, party-entries, re-record,
    withdraw, payments, continue, terminate, plat/ucc/copy creation)."""
    return build_user_headers(user_id, "Submitter")


# --- Opaque-role builders (let tests vary the opaque operator id, e.g. for
#     segregation-of-duties where recorder X-User-ID must differ from examiner) ---
def make_examiner_headers(user_id: str = "ex-1") -> dict:
    return build_user_headers(user_id, "Examiner")


def make_recorder_headers(user_id: str = "rec-1") -> dict:
    return build_user_headers(user_id, "Recorder")


def make_clerk_headers(user_id: str = "clerk-1") -> dict:
    return build_user_headers(user_id, "Clerk")
