"""Pre-built role headers for every role in the PRD (§2.1).

- Operator identity is opaque: the shared constant is the canonical form and
  works for every Operator-authorized call.
- GroupLeader is entity_backed:GroupLeader — ownership checks compare a
  departure's group_leader_id to X-User-ID, so ownership-gated calls MUST use
  make_group_leader_headers(group_leader["id"]).
- Traveler is entity_backed:Enrollment — ownership checks compare the target
  enrollment's id to X-User-ID, so ownership-gated calls MUST use
  make_traveler_headers(enrollment["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque Operator role, and for tests that do
# not exercise resource ownership (e.g. 401/403/404 on-bad-input).
TEST_USERS = {
    "operator_headers": build_user_headers("op-staff-1", "Operator"),
    # Fallbacks for non-ownership tests only.
    "group_leader_headers": build_user_headers("gl-fallback-1", "GroupLeader"),
    "traveler_headers": build_user_headers("traveler-fallback-1", "Traveler"),
}

OPERATOR = TEST_USERS["operator_headers"]

# A request that carries an X-User-ID but no valid X-User-Role (PRD §2.1: a
# missing/invalid X-User-Role yields ERR_UNAUTHENTICATED).
ANON_HEADERS = {"X-User-ID": "anon-user-1", "Content-Type": "application/json"}


def make_operator_headers(user_id: str = "op-staff-1") -> dict:
    return build_user_headers(user_id, "Operator")


def make_group_leader_headers(user_id: str) -> dict:
    """For GroupLeader (entity_backed:GroupLeader). Pass the actual GroupLeader.id
    whenever the call is ownership-gated on the departure's group_leader_id."""
    return build_user_headers(user_id, "GroupLeader")


def make_traveler_headers(user_id: str) -> dict:
    """For Traveler (entity_backed:Enrollment). Pass the actual Enrollment.id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Traveler")
