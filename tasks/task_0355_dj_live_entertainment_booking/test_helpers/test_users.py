"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the two opaque operator roles (StudioAdmin,
# BookingAgent), and for tests that do not exercise resource ownership.
# Performer and Client are entity-backed: the shared constant is only a fallback
# for non-ownership tests (e.g., 403-by-role, 404-on-missing). Ownership-gated
# calls MUST use the per-instance builders below threaded with the real id.
TEST_USERS = {
    "studio_admin_headers": build_user_headers("admin-1", "StudioAdmin"),
    "booking_agent_headers": build_user_headers("agent-1", "BookingAgent"),
    "performer_headers": build_user_headers("performer-fallback-1", "Performer"),
    "client_headers": build_user_headers("client-fallback-1", "Client"),
}


def make_studio_admin_headers(user_id: str = "admin-1") -> dict:
    """StudioAdmin is opaque; X-User-ID is never matched to an entity id."""
    return build_user_headers(user_id, "StudioAdmin")


def make_booking_agent_headers(user_id: str = "agent-1") -> dict:
    """BookingAgent is opaque; X-User-ID is never matched to an entity id."""
    return build_user_headers(user_id, "BookingAgent")


def make_performer_headers(user_id: str) -> dict:
    """For Performer (entity_backed:Performer). Pass the actual Performer.id as
    user_id whenever the call is ownership-gated (backup accept/decline, own
    blackouts)."""
    return build_user_headers(user_id, "Performer")


def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id as user_id
    whenever the call is ownership-gated (sign/decline contract, request
    revision, song requests, pay/capture, client-initiated cancel)."""
    return build_user_headers(user_id, "Client")
