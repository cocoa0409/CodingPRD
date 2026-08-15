"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. For entity-backed callers (Operator, CrewMember) on ownership- or
# scope-gated calls, ALWAYS use the per-instance builders below with the actual
# entity's id.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "SystemAdmin"),
    "marshal_headers": build_user_headers("fm_1", "FireMarshal"),
    "marshal2_headers": build_user_headers("fm_2", "FireMarshal"),
    # Fallback for non-ownership tests only (e.g. 400/404 probes).
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    "crew_headers": build_user_headers("test-crew-1", "CrewMember"),
}


def make_operator_headers(operator_id: str) -> dict:
    """For Operator (entity-backed by Operator). Pass the actual Operator.id
    whenever the call is ownership-gated."""
    return build_user_headers(operator_id, "Operator")


def make_crew_member_headers(crew_member_id: str) -> dict:
    """For CrewMember (entity-backed by CrewMember). Pass the actual
    CrewMember.id whenever the call is scope-gated."""
    return build_user_headers(crew_member_id, "CrewMember")


def make_marshal_headers(user_id: str) -> dict:
    """For FireMarshal (opaque identity). Distinct ids drive segregation-of-
    duties checks (approver vs standby confirmer, reporter vs closer)."""
    return build_user_headers(user_id, "FireMarshal")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For SystemAdmin (opaque identity)."""
    return build_user_headers(user_id, "SystemAdmin")
