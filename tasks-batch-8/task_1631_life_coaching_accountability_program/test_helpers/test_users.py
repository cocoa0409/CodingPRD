"""Pre-built role headers for every role in PRD §2.1.

Coach and Client are entity-backed roles: their X-User-ID must equal the id
of the acting Coach/Client row whenever the call is ownership-gated (e.g. a
coach completing their own session, a client pausing their own enrollment).
Fixtures MUST use make_coach_headers(coach["id"]) / make_client_headers(
client["id"]) for those calls; the shared constants below are only safe for
negative RBAC probes and for calls with no ownership dimension.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "practice_manager_headers": build_user_headers("pm-1", "PracticeManager"),
    # entity_backed:Coach — fallback for non-ownership probes only.
    "coach_headers": build_user_headers("coach-orphan-1", "Coach"),
    # entity_backed:Client — fallback for non-ownership probes only.
    "client_headers": build_user_headers("client-orphan-1", "Client"),
}

# A request with no auth headers at all (ERR_UNAUTHENTICATED probes).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}

# A well-formed id with a role value outside the declared set.
UNKNOWN_ROLE_HEADERS = {
    "X-User-ID": "anon-1",
    "X-User-Role": "SuperUser",
    "Content-Type": "application/json",
}


def make_coach_headers(coach_id: str) -> dict:
    """Coach is entity-backed by Coach: pass the acting coach's id whenever
    the call is ownership-gated (complete/mark-no-show own calls or sessions,
    cohort facilitation, filing a fit assessment)."""
    return build_user_headers(coach_id, "Coach")


def make_client_headers(client_id: str) -> dict:
    """Client is entity-backed by Client: pass the acting client's id
    whenever the call is ownership-gated (pause/resume/cancel own enrollment,
    cancel/reschedule own session, check-ins, testimonial consent)."""
    return build_user_headers(client_id, "Client")
