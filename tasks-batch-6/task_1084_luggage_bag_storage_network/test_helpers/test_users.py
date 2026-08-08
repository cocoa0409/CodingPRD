"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlatformAdmin) and for tests that do not
# exercise ownership (e.g. 401/403/404 checks). Host and Traveler are entity_backed:
# for ownership-gated calls use the make_*_headers builders with the real entity id.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "host_headers": build_user_headers("test-host-1", "Host"),
    "traveler_headers": build_user_headers("test-traveler-1", "Traveler"),
}

# Anonymous self-registration carries no auth headers.
ANON_HEADERS: dict = {}


def make_host_headers(user_id: str) -> dict:
    """For Host (entity_backed:Host). Pass the actual Host.id whenever the call is
    ownership-gated (location create, dropoff, pickup, etc.)."""
    return build_user_headers(user_id, "Host")


def make_traveler_headers(user_id: str) -> dict:
    """For Traveler (entity_backed:Traveler). Pass the actual Traveler.id whenever the
    call is ownership-gated (booking create/cancel, extension, claim, rating)."""
    return build_user_headers(user_id, "Traveler")


def make_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]
