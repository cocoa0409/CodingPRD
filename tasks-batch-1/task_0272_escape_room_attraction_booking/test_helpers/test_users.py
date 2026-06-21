"""Pre-built role headers for every role in the PRD (Section 2.1).

PlatformAdmin and VenueManager are opaque operator identities: X-User-ID is never
matched against any stored record, so the shared constants are the canonical form.

GameMaster and Customer are entity-backed: ownership checks compare X-User-ID to a
persisted entity's id. For ownership-gated calls, fixtures MUST use the per-instance
builders (make_game_master_headers / make_customer_headers) with the real entity id —
the shared constants are a fallback only for tests that do not exercise ownership
(e.g. 401/404/422 probes).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin", "PlatformAdmin"),
    "venue_manager_headers": build_user_headers("test-venue-manager", "VenueManager"),
    # Entity-backed roles — shared constant is a non-ownership fallback only.
    "game_master_headers": build_user_headers("test-game-master", "GameMaster"),
    "customer_headers": build_user_headers("test-customer", "Customer"),
}


# Per-instance builders for entity-backed roles.
def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the real Customer.id whenever the
    call is ownership-gated (booking/participant/waiver actions)."""
    return build_user_headers(customer_id, "Customer")


def make_game_master_headers(game_master_id: str) -> dict:
    """For GameMaster (entity_backed:GameMaster). Pass the real GameMaster.id for the
    on-site experience actions (mark-present, check-in, complete, no-show)."""
    return build_user_headers(game_master_id, "GameMaster")
