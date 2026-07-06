"""Pre-built role headers for every role in the PRD (§2.1).

- PlatformAdmin is an opaque operator identity — the shared constant is canonical.
- Farm and Customer are entity_backed: ownership checks compare X-User-ID against the
  Farm.id / Customer.id. Fixtures MUST call make_farm_headers(farm["id"]) /
  make_customer_headers(customer["id"]) with the real entity id for ownership-gated calls;
  the shared constants below are only safe for non-ownership tests (401/403/404 probes).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator — canonical form (never tied to an entity id).
    "admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    # entity_backed fallbacks — for tests that do NOT exercise ownership.
    "farm_headers": build_user_headers("00000000-0000-4000-8000-0000000000f1", "Farm"),
    "customer_headers": build_user_headers("00000000-0000-4000-8000-0000000000c1", "Customer"),
}


def make_admin_headers() -> dict:
    """PlatformAdmin headers (opaque identity)."""
    return TEST_USERS["admin_headers"]


def make_farm_headers(user_id: str) -> dict:
    """Farm role headers. Pass the acting Farm.id (entity_backed) so ownership checks pass."""
    return build_user_headers(user_id, "Farm")


def make_customer_headers(user_id: str) -> dict:
    """Customer role headers. Pass the acting Customer.id (entity_backed) so ownership checks pass."""
    return build_user_headers(user_id, "Customer")


# Absent-header request (missing X-User-Role / X-User-ID) for ERR_UNAUTHENTICATED probes.
ANONYMOUS_HEADERS: dict = {}
