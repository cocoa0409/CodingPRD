"""Pre-built role headers for every role in the PRD (§2.1).

Three roles per PRD §2.1:
  - Guest (identity: entity_backed:Guest) — X-User-ID must equal the acting Guest.id
  - Restaurant (identity: entity_backed:Restaurant) — X-User-ID must equal the acting Restaurant.id
  - PlatformAdmin (identity: opaque) — X-User-ID is an arbitrary operator string

For Guest and Restaurant, the shared TEST_USERS constants are only safe for
non-ownership tests (e.g., 401/403/404 on bad inputs). Tests whose success
requires the caller to own the underlying resource MUST use the per-instance
builders make_guest_headers(guest_id) / make_restaurant_headers(restaurant_id)
with the actual entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# ─── Shared constants ─────────────────────────────────────────────────────

TEST_USERS = {
    # entity_backed roles: fallback constants for non-ownership tests only
    "guest_headers": build_user_headers("test-guest-1", "Guest"),
    "restaurant_headers": build_user_headers("test-restaurant-1", "Restaurant"),
    # opaque role: shared constant is canonical
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


# ─── Per-instance builders (mandatory for entity_backed roles) ────────────

def make_guest_headers(guest_id: str) -> dict:
    """Build a Guest header bound to a specific Guest.id.
    Required whenever the request is ownership-gated on the acting guest."""
    return build_user_headers(guest_id, "Guest")


def make_restaurant_headers(restaurant_id: str) -> dict:
    """Build a Restaurant header bound to a specific Restaurant.id.
    Required whenever the request is ownership-gated on the acting restaurant."""
    return build_user_headers(restaurant_id, "Restaurant")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    """Build a PlatformAdmin header. Identity is opaque; any string is acceptable."""
    return build_user_headers(user_id, "PlatformAdmin")
