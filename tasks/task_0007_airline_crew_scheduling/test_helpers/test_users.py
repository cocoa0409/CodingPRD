"""Pre-built role headers for every role in the PRD.

Per PRD §2.1:
- `SchedulingPlanner` is opaque: X-User-ID is an opaque operator identifier,
  not compared against any entity id. The shared constant is canonical.
- `OperationsController` is opaque: same as SchedulingPlanner. Shared constant
  is canonical.
- `CrewMember` is entity_backed: the X-User-ID header MUST equal the acting
  CrewMember.id for ownership-gated calls (POST /bids, POST /assignments/{id}/confirm,
  POST /sick-calls, POST /reserve-callups/{id}/accept|decline, POST /trip-trades,
  POST /trip-trades/{id}/countersign|reject|withdraw). Use `make_crew_member_headers(cm_id)`
  with the actual CrewMember.id whenever the call is ownership-gated. The shared
  `crew_member_headers` constant is only safe for non-ownership tests.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS: dict = {
    # Opaque roles — shared constant is canonical (PRD §2.1).
    "scheduling_planner_headers": build_user_headers("planner-1", "SchedulingPlanner"),
    "operations_controller_headers": build_user_headers("ops-1", "OperationsController"),
    # Entity-backed CrewMember — shared constant is a fallback for non-ownership
    # tests only; ownership-gated calls MUST use make_crew_member_headers(cm_id).
    "crew_member_headers": build_user_headers("test-crew-fallback", "CrewMember"),
}


def make_crew_member_headers(crew_member_id: str) -> dict:
    """Required for any CrewMember-role call whose target resource is owned by
    the crew member — POST /bids (must match crew_member_id), POST /bids/{id}/withdraw,
    POST /assignments/{id}/confirm, POST /sick-calls, POST /reserve-callups/{id}/accept,
    POST /reserve-callups/{id}/decline, POST /trip-trades, POST /trip-trades/{id}/countersign,
    POST /trip-trades/{id}/reject, POST /trip-trades/{id}/withdraw.
    """
    return build_user_headers(crew_member_id, "CrewMember")


def make_unauthenticated_headers() -> dict:
    """Headers that deliberately omit X-User-Role to trigger ERR_UNAUTHENTICATED."""
    return {"Content-Type": "application/json"}
