"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed (Attendee, Exhibitor): for ownership-gated calls
the X-User-ID must equal the acting entity's own id, so those calls MUST use the
per-instance builders below with the real entity id. The remaining roles
(ConventionAdmin, RegistrationAgent, Anonymous) are opaque operator identities.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ConventionAdmin"),
    "agent_headers": build_user_headers("test-agent-1", "RegistrationAgent"),
    # Opaque self-registration caller. Self-register endpoints accept an
    # unauthenticated caller; supplying the Anonymous role is the canonical form.
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # Fallbacks for NON-ownership tests only (e.g. 401/403/404 on a foreign resource).
    "attendee_headers": build_user_headers("test-attendee-1", "Attendee"),
    "exhibitor_headers": build_user_headers("test-exhibitor-1", "Exhibitor"),
}


# Per-instance builders — required for every entity-backed role.

def make_attendee_headers(attendee_id: str) -> dict:
    """For the Attendee role (entity_backed:Attendee). Pass the real Attendee.id
    as X-User-ID whenever the call is ownership-gated (orders, badges,
    reservations, waitlist entries owned by this attendee)."""
    return build_user_headers(attendee_id, "Attendee")


def make_exhibitor_headers(exhibitor_id: str) -> dict:
    """For the Exhibitor role (entity_backed:Exhibitor). Pass the real
    Exhibitor.id as X-User-ID whenever the call is ownership-gated
    (booth bookings owned by this exhibitor)."""
    return build_user_headers(exhibitor_id, "Exhibitor")


def admin_headers() -> dict:
    return TEST_USERS["admin_headers"]


def agent_headers() -> dict:
    return TEST_USERS["agent_headers"]


def anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]
