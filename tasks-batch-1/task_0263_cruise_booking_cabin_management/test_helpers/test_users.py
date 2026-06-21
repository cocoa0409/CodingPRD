"""Pre-built role headers for every role in the Cruise Booking PRD.

RevenueManager, ReservationsAgent, and PortAgent carry opaque identities, so
the shared constants are canonical. GuestUser is entity-backed by the booking
it owns (X-User-ID must equal the booking's owner_user_id), so ownership-gated
calls MUST use make_guest_user_headers(owner_user_id) with the exact value used
as owner_user_id at booking creation.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "revenue_manager_headers": build_user_headers("rm-1", "RevenueManager"),
    "reservations_agent_headers": build_user_headers("ra-1", "ReservationsAgent"),
    "port_agent_headers": build_user_headers("pa-1", "PortAgent"),
    # GuestUser shared constant — only safe for tests that do NOT exercise
    # booking ownership (e.g. 400/403/404 before the ownership check, or RBAC
    # denial). Ownership-gated calls must use make_guest_user_headers().
    "guest_user_headers": build_user_headers("guest-shared", "GuestUser"),
}


def make_guest_user_headers(owner_user_id: str) -> dict:
    """Headers for a GuestUser (entity_backed:Booking).

    Pass the exact owner_user_id stored on the booking so the ownership check
    (Booking.owner_user_id == X-User-ID) passes.
    """
    return build_user_headers(owner_user_id, "GuestUser")
