"""Pre-built role headers for every role in the PRD (§2.1).

AquaticsManager and GateAttendant use opaque identifiers; Lifeguard and
PassHolder are entity-backed — use the per-instance builders with the actual
entity id whenever the call is ownership- or identity-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# entity identity (400-on-bad-payload, 404-on-missing-resource, RBAC denials).
TEST_USERS = {
    # opaque role: canonical form
    "manager_headers": build_user_headers("test-manager-1", "AquaticsManager"),
    # opaque role: canonical form
    "gate_headers": build_user_headers("test-gate-1", "GateAttendant"),
    # entity_backed:Lifeguard — fallback for non-identity tests only
    "lifeguard_headers": build_user_headers("test-lifeguard-1", "Lifeguard"),
    # entity_backed:PassHolder — fallback for non-ownership tests only
    "passholder_headers": build_user_headers("test-passholder-1", "PassHolder"),
}


def make_lifeguard_headers(user_id: str) -> dict:
    """For Lifeguard (entity-backed). Pass the actual Lifeguard.id whenever the
    call is identity-gated (shift check-in, incident submission, chemistry)."""
    return build_user_headers(user_id, "Lifeguard")


def make_passholder_headers(user_id: str) -> dict:
    """For PassHolder (entity-backed). Pass the actual PassHolder.id whenever
    the call is ownership-gated (enrollment drop, rental cancel/create)."""
    return build_user_headers(user_id, "PassHolder")
