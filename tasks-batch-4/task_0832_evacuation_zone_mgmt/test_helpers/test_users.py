"""Pre-built role headers for every role in the PRD.

Every role's identity is an opaque operator identifier (PRD 2.1): the server never
compares X-User-ID to any resource id, so a shared constant per role is correct for
every test. There are no ownership-gated (entity-backed) roles in this domain.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "commander_headers": build_user_headers("test-commander-1", "IncidentCommander"),
    "shelter_headers": build_user_headers("test-shelter-1", "ShelterCoordinator"),
    "traffic_headers": build_user_headers("test-traffic-1", "TrafficManager"),
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "pio_headers": build_user_headers("test-pio-1", "PublicInfoOfficer"),
}
