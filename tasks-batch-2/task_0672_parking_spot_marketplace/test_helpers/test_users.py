"""Pre-built role headers for every role in the PRD (§2.1).

Roles:
  - Host          → entity_backed:Host   (ownership-gated; needs per-instance builder)
  - Driver        → entity_backed:Driver (ownership-gated; needs per-instance builder)
  - PlatformAdmin → opaque (X-User-ID not compared to any entity)
  - Anonymous     → opaque (registration + clock only)
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
#   - admin / anonymous: opaque identities — the canonical form.
#   - host / driver: shared fallback ONLY for tests that do not exercise ownership
#     (e.g. 400 bad-payload, 403 forbidden-role, 404 missing-resource). For any
#     ownership-gated call, use the per-instance builders below with the real entity id.
TEST_USERS = {
    "host_headers": build_user_headers("test-host-1", "Host"),
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


# Per-instance builders — required for every entity_backed role.
def make_host_headers(host_id: str) -> dict:
    """For Host (entity_backed:Host). Pass the actual Host.id whenever the call is
    ownership-gated (spot create/unlist/relist, ledger read)."""
    return build_user_headers(host_id, "Host")


def make_driver_headers(driver_id: str) -> dict:
    """For Driver (entity_backed:Driver). Pass the actual Driver.id whenever the call is
    ownership-gated (booking actions, transfer accept/decline/withdraw, gate redeem)."""
    return build_user_headers(driver_id, "Driver")


def make_admin_headers() -> dict:
    """PlatformAdmin is opaque; identity is not compared to any entity."""
    return TEST_USERS["admin_headers"]


def make_anonymous_headers() -> dict:
    """Anonymous is opaque; used for registration and clock-set."""
    return TEST_USERS["anonymous_headers"]
