"""Pre-built role headers for every role in the PRD (Section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (ElectionAdmin, CustodyOfficer, SupportAgent),
# and for PrecinctCaptain/PollWorker on operations that are not per-worker ownership-gated.
TEST_USERS = {
    # Opaque operator roles — X-User-ID is not compared to any entity id (PRD Section 2.1).
    "election_admin_headers": build_user_headers("00000000-0000-4000-8000-00000000ad01", "ElectionAdmin"),
    "custody_officer_headers": build_user_headers("00000000-0000-4000-8000-00000000c001", "CustodyOfficer"),
    "support_agent_headers": build_user_headers("00000000-0000-4000-8000-00000000a501", "SupportAgent"),
    # entity_backed roles — shared constant is a fallback for non-ownership tests only.
    "precinct_captain_headers": build_user_headers("00000000-0000-4000-8000-0000000000c1", "PrecinctCaptain"),
    "poll_worker_headers": build_user_headers("00000000-0000-4000-8000-0000000000e1", "PollWorker"),
}

# Header with an unrecognized role -> triggers ERR_UNAUTHENTICATED (PRD Section 2.1).
ANONYMOUS_HEADERS = build_user_headers("00000000-0000-4000-8000-000000000000", "Anonymous")


def make_precinct_captain_headers(user_id: str) -> dict:
    """For PrecinctCaptain (entity_backed:PollWorker). Pass the acting PollWorker.id as
    user_id when a call is ownership-gated on the acting worker."""
    return build_user_headers(user_id, "PrecinctCaptain")


def make_poll_worker_headers(user_id: str) -> dict:
    """For PollWorker (entity_backed:PollWorker). Pass the acting PollWorker.id as user_id
    when a call is ownership-gated on the acting worker (e.g. checking into one's own shift)."""
    return build_user_headers(user_id, "PollWorker")
