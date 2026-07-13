"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Dispatcher, Driver, EligibilitySpecialist,
# Admin) whose X-User-ID is never compared to any entity id. The generic Rider header
# is a fallback ONLY for tests that do not exercise ownership; ownership-gated Rider
# calls MUST use make_rider_headers(rider["id"]).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    "specialist_headers": build_user_headers("test-specialist-1", "EligibilitySpecialist"),
    "rider_headers": build_user_headers("test-rider-1", "Rider"),
    # Deliberately unrecognized role for ERR_UNAUTHENTICATED tests.
    "unknown_role_headers": build_user_headers("test-ghost-1", "Ghost"),
}


def make_rider_headers(user_id: str) -> dict:
    """For the Rider role (identity entity_backed:Rider). Pass the acting Rider's
    actual id as user_id whenever the call is ownership-gated (trip create/counter/
    accept/cancel, subscription create/cancel, appeal by rider)."""
    return build_user_headers(user_id, "Rider")
