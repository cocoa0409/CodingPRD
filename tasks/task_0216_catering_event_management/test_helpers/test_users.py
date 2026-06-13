"""Pre-built role headers for every role in the Catering Event Management PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (CateringAdmin, SalesCoordinator, EventCaptain),
# and for Client tests that do NOT exercise ownership (e.g. 400/403/404 negative cases).
TEST_USERS = {
    "admin_headers": build_user_headers("admin-op-1", "CateringAdmin"),
    "coordinator_headers": build_user_headers("coord-op-1", "SalesCoordinator"),
    "captain_headers": build_user_headers("captain-op-1", "EventCaptain"),
    # Client is entity_backed: this shared constant is a non-ownership fallback only.
    "client_headers": build_user_headers("test-client-1", "Client"),
}


# Per-instance builder — REQUIRED for the entity_backed Client role. Pass the actual
# Client.id whenever the call is ownership-gated (orders/change-requests acted on by a Client).
def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id as user_id whenever the
    call is ownership-gated (PRD §2.1: order's client_id must equal X-User-ID)."""
    return build_user_headers(user_id, "Client")


# The three opaque roles never carry an entity-bound identity; convenience builders
# for parametrized RBAC tests that need a role string.
def make_admin_headers(user_id: str = "admin-op-1") -> dict:
    return build_user_headers(user_id, "CateringAdmin")


def make_coordinator_headers(user_id: str = "coord-op-1") -> dict:
    return build_user_headers(user_id, "SalesCoordinator")


def make_captain_headers(user_id: str = "captain-op-1") -> dict:
    return build_user_headers(user_id, "EventCaptain")
