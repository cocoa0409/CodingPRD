"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   Dispatcher and Biller are opaque operator identities not tied to any entity,
#   so the shared constant is the canonical form.
#   Driver is entity_backed:Driver — the shared constant is a fallback usable only
#   for tests that do NOT exercise leg ownership; ownership-gated calls MUST use
#   make_driver_headers(driver_id) with the acting driver's real id.
TEST_USERS = {
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "biller_headers": build_user_headers("biller-1", "Biller"),
    "driver_headers": build_user_headers("driver-shared-1", "Driver"),
}


def make_driver_headers(user_id: str) -> dict:
    """For the Driver role (entity_backed:Driver). Pass the acting Driver.id as
    user_id whenever the call is ownership-gated (e.g. POST /legs/{id}/complete)."""
    return build_user_headers(user_id, "Driver")
