"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - FareAdmin and Conductor use opaque X-User-ID; the shared constant is canonical.
#   - Passenger is entity_backed: the shared constant is a fallback for tests that do
#     NOT exercise ownership (e.g. RBAC-denied-by-role). Ownership-gated Passenger calls
#     MUST use make_passenger_headers(passenger_id) with the real Passenger.id.
TEST_USERS = {
    "fareadmin_headers": build_user_headers("test-admin-1", "FareAdmin"),
    "conductor_headers": build_user_headers("test-conductor-1", "Conductor"),
    "passenger_headers": build_user_headers("test-passenger-1", "Passenger"),
}


def make_passenger_headers(user_id: str) -> dict:
    """For the Passenger role (entity_backed:Passenger). Pass the actual Passenger.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Passenger")


def make_conductor_headers(user_id: str = "test-conductor-1") -> dict:
    return build_user_headers(user_id, "Conductor")


def make_fareadmin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "FareAdmin")
