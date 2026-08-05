"""Pre-built role headers for every role in the PRD (§2.1).

StateCoordinator is opaque (X-User-ID not tied to any entity); Liaison,
TransportCoordinator, and Registrar are entity-backed, so ownership-gated
calls must thread the actual entity id via the per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise
# ownership (role-permission 403 checks, 404-on-missing-resource, etc.).
TEST_USERS = {
    "state_coordinator_headers": build_user_headers("state-coordinator-1", "StateCoordinator"),
    "liaison_headers": build_user_headers("test-liaison-1", "Liaison"),
    "transport_coordinator_headers": build_user_headers("test-district-tc-1", "TransportCoordinator"),
    "registrar_headers": build_user_headers("test-district-reg-1", "Registrar"),
}


# Per-instance builders — required for every entity-backed role.
def make_liaison_headers(liaison_id: str) -> dict:
    """For Liaison (entity_backed:Liaison). Pass the acting Liaison.id."""
    return build_user_headers(liaison_id, "Liaison")


def make_transport_coordinator_headers(district_id: str) -> dict:
    """For TransportCoordinator (entity_backed:District). Pass the acting District.id."""
    return build_user_headers(district_id, "TransportCoordinator")


def make_registrar_headers(district_id: str) -> dict:
    """For Registrar (entity_backed:District). Pass the acting District.id."""
    return build_user_headers(district_id, "Registrar")
