"""Pre-built role headers for every role in the PRD.

Dispatcher is an opaque operator: its X-User-ID is not tied to any persisted entity,
so the shared constant is the canonical form for all Dispatcher calls.

Rider and Driver are entity_backed: their X-User-ID must equal the acting entity's id
for ownership-gated calls (a rider's id == the trip's rider_id; a driver's id ==
the trip's driver_id, or the queue entry's driver_id). Use make_rider_headers(id) /
make_driver_headers(id) with the real entity id whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque Dispatcher, and for non-ownership tests.
TEST_USERS = {
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "rider_headers": build_user_headers("test-rider-1", "Rider"),
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    """Dispatcher is opaque; user_id is not compared to any entity."""
    return build_user_headers(user_id, "Dispatcher")


def make_rider_headers(user_id: str) -> dict:
    """For a Rider (entity_backed). Pass the actual Rider.id for ownership-gated calls."""
    return build_user_headers(user_id, "Rider")


def make_driver_headers(user_id: str) -> dict:
    """For a Driver (entity_backed). Pass the actual Driver.id for ownership-gated calls."""
    return build_user_headers(user_id, "Driver")


def anonymous_headers() -> dict:
    """Headers with no X-User-Role — for ERR_UNAUTHENTICATED tests."""
    return {"X-User-ID": "anon-1", "Content-Type": "application/json"}
